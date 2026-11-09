import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import psutil
import pytest

from app.services.local_runtime import (
    RuntimeErrorState, RuntimeLock, Service, Supervisor, check_ports,
    runtime_status, service_specs, write_json,
)


def test_singleton_blocks_other_process_and_releases_after_crash(tmp_path):
    lock = tmp_path / 'runtime.lock'
    script = 'from app.services.local_runtime import RuntimeLock; import sys,time; lock=RuntimeLock(sys.argv[1]); lock.__enter__(); print(__import__("os").getpid(),flush=True); time.sleep(30)'
    process = psutil.Popen([sys.executable, '-u', '-c', script, str(lock)], stdout=subprocess.PIPE, text=True)
    interpreter = None
    try:
        interpreter = psutil.Process(int(process.stdout.readline().strip()))
        with pytest.raises(RuntimeErrorState, match='Another'):
            with RuntimeLock(lock):
                pass
    finally:
        if interpreter is not None:
            interpreter.terminate()
            interpreter.wait(timeout=10)
        else:
            process.terminate()
        process.wait(timeout=10)
        process.stdout.close()
    with RuntimeLock(lock):
        assert lock.exists()


def test_owned_process_tree_stops_but_unrelated_process_survives(tmp_path):
    child = tmp_path / 'child.json'
    script = ('import subprocess,sys,time,json,psutil; '
              'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"]); '
              'open(sys.argv[1],"w").write(json.dumps([p.pid,psutil.Process(p.pid).create_time()])); time.sleep(90)')
    supervisor = Supervisor(tmp_path, sys.executable, os.environ.copy(),
                            services=[Service('tree', ('-c', script, str(child)))])
    unrelated = psutil.Popen([sys.executable, '-c', 'import time;time.sleep(90)'])
    try:
        supervisor.tick()
        deadline = time.monotonic() + 15
        while not child.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert child.exists()
        # File is small, but allow the child to finish writing its JSON.
        for _ in range(50):
            try:
                child_pid, child_created = json.loads(child.read_text())
                break
            except ValueError:
                time.sleep(.02)
        descendant = psutil.Process(child_pid)
        assert descendant.create_time() == child_created
        supervisor.services[0].remember_children()
        supervisor.stop()
        assert not descendant.is_running() or descendant.status() == psutil.STATUS_ZOMBIE
        assert unrelated.is_running()
    finally:
        supervisor.stop()
        unrelated.terminate()
        unrelated.wait(timeout=10)


def test_failing_child_backs_off_and_exhausts_restart_budget(tmp_path):
    clock = [100.0]
    supervisor = Supervisor(tmp_path, sys.executable, os.environ.copy(),
                            services=[Service('broken', ('-c', 'raise SystemExit(7)'))],
                            clock=lambda: clock[0])
    try:
        for attempt in range(4):
            supervisor.tick()
            service = supervisor.services[0]
            assert service.attempts == attempt + 1
            service.process.wait(timeout=10)
            if attempt == 3:
                with pytest.raises(RuntimeErrorState, match='three restarts'):
                    supervisor.tick()
            else:
                assert supervisor.tick() == 'degraded'
                assert service.state == 'backoff'
                supervisor.tick()
                assert service.attempts == attempt + 1
                clock[0] = service.next_start
        assert service.last_exit_code == 7
    finally:
        supervisor.stop()
    state = json.loads((supervisor.directory / 'status.json').read_text())
    assert state['status'] == 'failed'
    assert state['failure'] == 'broken_restart_budget_exhausted'


def test_unhealthy_http_child_is_restarted_after_grace(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('app.services.local_runtime.probe', lambda *_: False)
    supervisor = Supervisor(tmp_path, sys.executable, os.environ.copy(),
                            services=[Service('hung', ('-c', 'import time;time.sleep(90)'), 'http', 'unused')],
                            clock=lambda: clock[0])
    try:
        assert supervisor.tick() == 'degraded'
        for now in (110, 120):
            clock[0] = now
            supervisor.tick()
            assert supervisor.services[0].state == 'starting'
        clock[0] = 161
        supervisor.tick()
        assert supervisor.services[0].state == 'backoff'
        assert supervisor.services[0].process is None
    finally:
        supervisor.stop()


def test_busy_port_is_refused_without_stopping_its_owner():
    with socket.socket() as unrelated:
        unrelated.bind(('127.0.0.1', 0))
        unrelated.listen()
        port = unrelated.getsockname()[1]
        with pytest.raises(RuntimeErrorState, match='already in use'):
            check_ports([port])
        assert unrelated.getsockname()[1] == port


def test_status_detects_stale_heartbeat_and_pid_reuse(tmp_path):
    path = tmp_path / 'status.json'
    current = psutil.Process()
    value = {'pid': current.pid, 'created_at': current.create_time(), 'updated_at': 100, 'status': 'running'}
    write_json(path, value)
    assert runtime_status(path, now=101)['status'] == 'running'
    assert runtime_status(path, now=131)['status'] == 'unresponsive'
    write_json(path, {**value, 'created_at': current.create_time() - 1})
    assert runtime_status(path, now=101)['status'] == 'stopped'


def test_stop_request_must_match_current_supervisor_token(tmp_path):
    supervisor = Supervisor(tmp_path, sys.executable, os.environ.copy(), services=[])
    write_json(supervisor.directory / 'stop.json', {'token': 'old-owner'})
    assert not supervisor.stop_requested()
    write_json(supervisor.directory / 'stop.json', {'token': supervisor.token})
    assert supervisor.stop_requested()


def test_service_commands_keep_private_listeners_and_all_three_workers():
    services = {s.name: s for s in service_specs()}
    assert set(services) == {'api', 'gateway', 'dashboard', 'replay', 'reviews', 'outcomes'}
    for name in ('api', 'gateway'):
        assert '127.0.0.1' in services[name].arguments
        assert '--no-access-log' in services[name].arguments
    assert '--server.address=127.0.0.1' in services['dashboard'].arguments
    for name in ('replay', 'reviews', 'outcomes'):
        assert '--watch' in services[name].arguments
        assert services[name].probe_kind is None  # Liveness, not a job-progress heartbeat.


def test_launcher_refuses_live_keys_before_starting_any_process(tmp_path, monkeypatch, capsys):
    from app.config import settings
    from scripts import run_local
    monkeypatch.setattr(settings, 'razorpay_key_id', 'rzp_live_fixture')
    monkeypatch.setattr(run_local, 'ROOT', tmp_path)
    assert run_local.main(['--check']) == 1
    assert 'requires Razorpay Test Mode' in capsys.readouterr().out


def test_launcher_requires_ready_database_without_running_migrations(tmp_path, monkeypatch, capsys):
    from scripts import run_local
    monkeypatch.setattr(run_local, 'ROOT', tmp_path)
    monkeypatch.setattr('app.services.readiness.check_readiness', lambda: {'status': 'not_ready', 'issues': ['schema_outdated']})
    assert run_local.main(['--check']) == 1
    assert 'schema_outdated' in capsys.readouterr().out
    assert not (tmp_path / 'var/runtime/status.json').exists()

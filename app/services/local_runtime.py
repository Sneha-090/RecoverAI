"""Owned local processes, bounded restarts, and an OS-released singleton lock.

No provider calls or application settings are loaded by this module.
"""

from collections import deque
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import build_opener, ProxyHandler
import uuid

import psutil


class RuntimeErrorState(RuntimeError):
    pass


class RuntimeLock(AbstractContextManager):
    """Hold a kernel file lock; a process crash releases it without stale expiry."""

    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeErrorState('Another local supervisor owns the runtime lock') from None
        return self

    def __exit__(self, *_):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def owner_alive(state):
    try:
        process = psutil.Process(state['pid'])
        return process.is_running() and process.create_time() == state['created_at']
    except (psutil.Error, KeyError, TypeError):
        return False


def runtime_status(path, now=None):
    state = read_json(path)
    if not state:
        return {'status': 'stopped'}
    if not owner_alive(state):
        return {**state, 'status': state['status'] if state.get('status') in {'failed', 'stop_failed'} else 'stopped'}
    if (now if now is not None else time.time()) - state.get('updated_at', 0) > 30:
        return {**state, 'status': 'unresponsive'}
    return state


def check_ports(ports):
    for port in ports:
        try:
            with socket.socket() as listener:
                if os.name == 'nt':
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeErrorState(f'Port {port} is already in use; no process was stopped') from None


def probe(kind, target):
    try:
        if kind == 'tcp':
            with socket.create_connection(('127.0.0.1', target), timeout=2):
                return True
        # Explicitly bypass system HTTP proxies for private loopback checks.
        with build_opener(ProxyHandler({})).open(target, timeout=2) as response:
            if kind == 'ready':
                return response.status == 200 and json.loads(response.read(4096))['status'] == 'ready'
            return response.status == 200
    except (OSError, ValueError, KeyError):
        return False


@dataclass(frozen=True)
class Service:
    name: str
    arguments: tuple
    probe_kind: str | None = None
    probe_target: str | int | None = None


def service_specs():
    return (
        Service('api', ('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001', '--no-access-log'),
                'ready', 'http://127.0.0.1:8001/ready'),
        Service('gateway', ('-m', 'uvicorn', 'app.webhook_gateway:app', '--host', '127.0.0.1', '--port', '8002', '--no-access-log'),
                'tcp', 8002),
        Service('dashboard', ('-m', 'streamlit', 'run', 'dashboard.py', '--server.address=127.0.0.1', '--server.port=8501',
                              '--server.headless=true', '--browser.gatherUsageStats=false'),
                'http', 'http://127.0.0.1:8501/_stcore/health'),
        Service('replay', ('-m', 'scripts.replay_webhooks', '--watch')),
        Service('reviews', ('-m', 'scripts.maintain_reviews', '--watch')),
        Service('outcomes', ('-m', 'scripts.poll_outcomes', '--watch')),
    )


@dataclass
class ManagedService:
    spec: Service
    process: object = None
    owned: dict = field(default_factory=dict)
    restarts: deque = field(default_factory=deque)
    started_at: float = 0
    next_start: float = 0
    healthy: bool = False
    failures: int = 0
    state: str = 'waiting'
    attempts: int = 0
    last_exit_code: int | None = None

    def remember_children(self):
        if self.process is None:
            return
        try:
            if self.process.is_running():
                for child in self.process.children(recursive=True):
                    self.owned[(child.pid, child.create_time())] = child
        except psutil.NoSuchProcess:
            pass

    def stop(self):
        """Signal only captured process identities, including Windows venv children."""
        self.remember_children()
        processes = list(self.owned.values())
        if self.process is not None:
            processes.append(self.process)
        for process in processes:
            try:
                process.terminate()  # psutil checks PID + creation time before signalling.
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(processes, timeout=3)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(alive, timeout=3)
        if alive:
            raise RuntimeErrorState('An owned process did not stop; manual inspection required')
        if self.process is not None:
            self.process.wait(timeout=1)
        self.process = None
        self.owned.clear()
        self.healthy = False


class Supervisor:
    def __init__(self, root, python, environment, *, services=None, clock=time.monotonic):
        self.root = Path(root)
        self.directory = self.root / 'var/runtime'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.python = str(python)
        self.environment = environment
        self.clock = clock
        self.token = uuid.uuid4().hex
        self.services = [ManagedService(s) for s in (services if services is not None else service_specs())]
        self.failure = None
        self.owner = psutil.Process()
        self.run_id = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + self.token[:8]
        self.log_directory = self.root / 'var/logs' / self.run_id
        self.log_directory.mkdir(parents=True)

    def snapshot(self, status):
        value = {
            'status': status, 'token': self.token, 'pid': self.owner.pid,
            'created_at': self.owner.create_time(), 'updated_at': time.time(),
            'logs': str(self.log_directory), 'failure': self.failure,
            'services': {s.spec.name: {
                'state': s.state, 'pid': s.process.pid if s.process else None,
                'starts': s.attempts, 'last_exit_code': s.last_exit_code,
                'monitor': s.spec.probe_kind or 'process_liveness',
            } for s in self.services},
        }
        write_json(self.directory / 'status.json', value)
        return value

    def start(self, service, now):
        with (self.log_directory / (service.spec.name + '.log')).open('ab', buffering=0) as log:
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            service.process = psutil.Popen(
                [self.python, *service.spec.arguments], cwd=self.root, env=self.environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs,
            )
        # Capture creation time before any possibility of PID reuse.
        service.process.create_time()
        service.started_at = now
        service.attempts += 1
        service.failures = 0
        service.healthy = not service.spec.probe_kind
        service.state = 'running' if service.healthy else 'starting'

    def failed(self, service, now):
        service.stop()
        while service.restarts and now - service.restarts[0] >= 600:
            service.restarts.popleft()
        if len(service.restarts) >= 3:
            service.state = 'failed'
            self.failure = service.spec.name + '_restart_budget_exhausted'
            raise RuntimeErrorState(f'{service.spec.name} exceeded three restarts in ten minutes')
        service.restarts.append(now)
        service.next_start = now + min(30, 2 ** len(service.restarts))
        service.state = 'backoff'

    def tick(self):
        now = self.clock()
        for service in self.services:
            if service.process is None:
                if now >= service.next_start:
                    self.start(service, now)
                continue
            service.remember_children()
            result = service.process.poll()
            if result is not None:
                service.last_exit_code = result
                self.failed(service, now)
                continue
            if service.spec.probe_kind:
                ok = probe(service.spec.probe_kind, service.spec.probe_target)
                service.healthy = ok
                service.state = 'running' if ok else 'starting' if now - service.started_at < 60 else 'unhealthy'
                service.failures = 0 if ok else service.failures + 1
                if now - service.started_at >= 60 and service.failures >= 3:
                    self.failed(service, now)
        return 'running' if all(s.healthy for s in self.services) else 'degraded'

    def stop_requested(self):
        request = read_json(self.directory / 'stop.json')
        return bool(request and request.get('token') == self.token)

    def stop(self):
        errors = []
        for service in reversed(self.services):
            try:
                service.stop()
                service.state = 'stopped'
            except (psutil.Error, RuntimeErrorState):
                service.state = 'stop_failed'
                errors.append(service.spec.name)
        self.snapshot('stop_failed' if errors else 'failed' if self.failure else 'stopped')
        if errors:
            raise RuntimeErrorState('Inspect owned processes that could not be stopped: ' + ', '.join(errors))


def find_existing_services(root):
    """Do not start extra workers beside manually launched copies from this repo."""
    markers = ('app.main:app', 'app.webhook_gateway:app', 'dashboard.py',
               'scripts.replay_webhooks', 'scripts.maintain_reviews', 'scripts.poll_outcomes')
    for process in psutil.process_iter(['pid', 'cmdline', 'cwd']):
        if process.pid == os.getpid():
            continue
        try:
            args = process.info['cmdline'] or []
            cwd = process.info['cwd']
            if cwd and Path(cwd).resolve() == Path(root).resolve() and any(marker in args for marker in markers):
                return True
        except (psutil.Error, OSError):
            continue
    return False

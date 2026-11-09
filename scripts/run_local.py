"""Start and supervise the private Test Mode app and its three workers."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

from app.services.local_runtime import (
    RuntimeErrorState, RuntimeLock, Supervisor, check_ports, find_existing_services,
    runtime_status, write_json, owner_alive,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--status', action='store_true')
    mode.add_argument('--stop', action='store_true')
    mode.add_argument('--check', action='store_true', help='Check setup without starting processes')
    args = parser.parse_args(argv)
    directory = ROOT / 'var/runtime'
    if args.status or args.stop:
        state = runtime_status(directory / 'status.json')
        if args.status:
            print(json.dumps(state))
            return 0 if state['status'] == 'running' else 1
        if not owner_alive(state):
            print(json.dumps({'status': 'already_stopped'}))
            return 0
        write_json(directory / 'stop.json', {'token': state['token']})
        print(json.dumps({'status': 'stop_requested'}))
        return 0

    stopped = threading.Event()
    supervisor = None
    try:
        with RuntimeLock(directory / 'supervisor.lock'):
            from app.config import settings
            from app.services.readiness import check_readiness
            if not settings.razorpay_key_id.startswith('rzp_test_'):
                raise RuntimeErrorState('This local launcher requires Razorpay Test Mode credentials')
            readiness = check_readiness()
            if readiness['status'] != 'ready':
                print(json.dumps(readiness))
                return 1
            if find_existing_services(ROOT):
                raise RuntimeErrorState('Existing RecoverAI processes found; stop their terminals before using the supervisor')
            check_ports((8001, 8002, 8501))
            if args.check:
                print(json.dumps({'status': 'checks_passed'}))
                return 0
            temporary = ROOT / 'var/tmp'
            temporary.mkdir(parents=True, exist_ok=True)
            environment = {**os.environ, 'TEMP': str(temporary), 'TMP': str(temporary),
                           'TMPDIR': str(temporary), 'PYTHONDONTWRITEBYTECODE': '1',
                           'PYTHONUNBUFFERED': '1', 'OPENBLAS_NUM_THREADS': '1',
                           'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                           'API_BASE_URL': 'http://127.0.0.1:8001'}
            supervisor = Supervisor(ROOT, sys.executable, environment)
            previous_handlers = {}
            try:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    previous_handlers[sig] = signal.signal(sig, lambda *_: stopped.set())
                previous_status = None
                while not stopped.is_set() and not supervisor.stop_requested():
                    status = supervisor.tick()
                    supervisor.snapshot(status)
                    if status != previous_status:
                        print(json.dumps({'status': status}), flush=True)
                        previous_status = status
                    stopped.wait(2)
            except Exception:
                supervisor.failure = supervisor.failure or 'local_runtime_error'
                raise
            finally:
                supervisor.stop()
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
        return 0
    except RuntimeErrorState as error:
        print(json.dumps({'status': 'stopped', 'reason': str(error)}), flush=True)
        return 1
    except Exception:
        print(json.dumps({'status': 'stopped', 'reason': 'Local runtime failed; inspect protected local logs and setup'}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

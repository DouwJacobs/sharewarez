"""Real HTTP streams in independent processes, including worker replacement."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from sharewarez import db
from sharewarez.models import DownloadTransfer, User
from sharewarez.utils.migrations import bootstrap_schema_extras


ROOT = Path(__file__).parents[1]


def _port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _launch(port):
    env = {**os.environ, 'DATABASE_URL': os.environ['TEST_DATABASE_URL']}
    process = subprocess.Popen([
        sys.executable, '-m', 'uvicorn', 'tests.live_worker_fixture:make_app', '--factory',
        '--host', '127.0.0.1', '--port', str(port), '--timeout-graceful-shutdown', '1', '--no-access-log',
    ], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f'Test worker exited: {process.returncode}')
        try:
            with urlopen(f'http://127.0.0.1:{port}/health/live', timeout=1) as response:
                if response.status == 200:
                    return process
        except OSError:
            time.sleep(0.05)
    process.terminate(); process.wait(timeout=5)
    raise AssertionError('Test worker did not become ready')


def _snapshot(response):
    while True:
        line = response.readline()
        assert line, 'SSE stream closed before a snapshot'
        if line.startswith(b'data: '):
            return json.loads(line[6:])


def test_two_workers_receive_commit_and_restarted_worker_resynchronizes(app, db_session):
    bootstrap_schema_extras(db.engine)
    suffix = uuid4().hex
    admin = User(name=f'worker-{suffix}', email=f'{suffix}@example.test', role='admin',
                 state=True, password_hash='test')
    db_session.add(admin); db_session.flush()
    transfer = DownloadTransfer(user_id=admin.id, filename='process-test.bin', bytes_sent=10, reserved_bytes=1000000)
    db_session.add(transfer); db_session.commit()
    transfer_id = transfer.id
    token = app.session_interface.get_signing_serializer(app).dumps({'_user_id':str(admin.id)})
    ports = [_port(), _port()]
    processes, streams = [], []
    def connect(port):
        return urlopen(Request(f'http://127.0.0.1:{port}/api/live/downloads?view=activity',
                               headers={'Cookie':f'session={token}'}), timeout=5)
    def observed(response):
        return next(item['bytes_sent'] for item in _snapshot(response)['transfers'] if item['id'] == transfer_id)
    try:
        for port in ports:
            processes.append(_launch(port))
            response = connect(port); streams.append(response)
            assert response.headers['Content-Type'].startswith('text/event-stream')
            assert observed(response) == 10
        transfer.bytes_sent = 123456
        transfer.last_activity_at = datetime.now(timezone.utc)
        db_session.commit()
        for response in streams:
            for _ in range(4):
                if observed(response) == 123456:
                    break
            else:
                raise AssertionError('Worker missed the committed transfer update')
        # Normal Flask requests still complete while each process holds an SSE stream.
        for port in ports:
            with urlopen(f'http://127.0.0.1:{port}/health/live', timeout=2) as response:
                assert response.status == 200
        processes[0].terminate(); processes[0].wait(timeout=5)
        streams[0].close()
        processes[0] = _launch(ports[0])
        streams[0] = connect(ports[0])
        assert observed(streams[0]) == 123456
    finally:
        for response in streams:
            response.close()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)

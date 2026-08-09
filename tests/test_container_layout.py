from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_uses_single_application_container():
    compose = yaml.safe_load((ROOT / 'docker-compose.yml').read_text(encoding='utf-8'))

    assert set(compose['services']) == {'app', 'db'}
    assert compose['services']['app']['init'] is True
    assert compose['services']['app']['read_only'] is True
    assert 'JOB_POLL_SECONDS=${JOB_POLL_SECONDS:-1}' in compose['services']['app']['environment']


def test_application_startup_supervises_web_and_job_processes():
    startup = (ROOT / 'startweb-docker.sh').read_text(encoding='utf-8')

    assert 'python3 -m sharewarez.job_worker &' in startup
    assert 'uvicorn asgi:asgi_app' in startup
    assert 'wait -n "$web_pid" "$job_pid"' in startup
    assert 'stop_children' in startup

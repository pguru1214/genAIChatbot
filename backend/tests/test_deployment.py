import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import deployment
from app.config import Settings
from app.main import app


@pytest.fixture
def public_settings(monkeypatch):
    import app.main as main
    settings = Settings(app_mode='demo', public_deployment=True,
        deployment_access_password='test-access-password-1234567890', session_signing_key='test-signing-key-' * 4)
    monkeypatch.setattr(deployment, 'get_settings', lambda: settings)
    monkeypatch.setattr(main, 'get_settings', lambda: settings)
    deployment._login_attempts.clear()
    return settings


def test_public_api_and_chat_are_private_until_login(public_settings):
    with TestClient(app, base_url='https://testserver') as client:
        assert client.get('/').status_code == 200
        assert 'Access password' in client.get('/').text
        assert client.get('/api/trips').status_code == 401
        assert client.get('/api/conversations').status_code == 401
        assert client.post('/api/conversations').status_code == 401
        health = client.get('/api/health').json()
        assert health['status'] == 'ok' and health['authentication'] == 'private-demo-access'
        assert 'password' not in str(health)


def test_access_login_cookie_and_greeting(public_settings):
    with TestClient(app, base_url='https://testserver') as client:
        response = client.post('/access', data={'password': public_settings.deployment_access_password}, follow_redirects=False)
        assert response.status_code == 303
        cookie = response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
        assert public_settings.deployment_access_password not in cookie
        assert client.get('/api/trips').status_code == 200
        cid = client.post('/api/conversations').json()['id']
        response = client.post(f'/api/conversations/{cid}/messages', json={'message': 'Hello'})
        assert 'event: completed' in response.text
        assert 'Hello!' in response.text


def test_invalid_and_tampered_access_are_rejected(public_settings):
    with TestClient(app, base_url='https://testserver') as client:
        assert client.post('/access', data={'password': 'wrong'}).status_code == 401
        value = deployment.signed_session(public_settings)
        assert deployment.valid_session(value, public_settings)
        assert not deployment.valid_session(value[:-1] + ('0' if value[-1] != '0' else '1'), public_settings)
        assert not deployment.valid_session(None, public_settings)
        for _ in range(4):
            assert client.post('/access', data={'password': 'wrong'}).status_code == 401
        assert client.post('/access', data={'password': 'wrong'}).status_code == 429


def test_cross_site_post_and_weak_config_fail_closed(public_settings, monkeypatch):
    with TestClient(app, base_url='https://testserver') as client:
        assert client.post('/access', data={'password': public_settings.deployment_access_password},
                           headers={'Origin': 'https://other-site.example'}).status_code == 403
        monkeypatch.setattr(public_settings, 'deployment_access_password', '')
        assert client.get('/api/trips').status_code == 503


def test_single_origin_static_host_preserves_api_routes(tmp_path, monkeypatch):
    (tmp_path / 'index.html').write_text('<h1>TripWeave</h1>', encoding='utf-8')
    settings = Settings(app_mode='demo', frontend_dist=str(tmp_path), public_deployment=False)
    monkeypatch.setattr(deployment, 'get_settings', lambda: settings)
    test_app = FastAPI()

    @test_app.get('/api/health')
    def health():
        return {'status': 'ok'}

    deployment.configure_deployment(test_app)
    with TestClient(test_app) as client:
        assert '<h1>TripWeave</h1>' in client.get('/').text
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/api/missing').status_code == 404
        assert client.get('/.env').status_code == 404

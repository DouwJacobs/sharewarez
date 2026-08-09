from sharewarez.security import limiter


def test_security_headers_are_applied(client):
    response = client.get('/login')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert response.headers['Cross-Origin-Opener-Policy'] == 'same-origin'
    assert "default-src 'self'" in response.headers['Content-Security-Policy']
    assert 'Strict-Transport-Security' not in response.headers


def test_hsts_is_applied_to_https(client):
    response = client.get('/login', base_url='https://localhost')

    assert response.headers['Strict-Transport-Security'].startswith('max-age=31536000')


def test_login_post_rate_limit(client):
    limiter.reset()
    for _ in range(10):
        assert client.post('/login', data={}).status_code != 429

    assert client.post('/login', data={}).status_code == 429

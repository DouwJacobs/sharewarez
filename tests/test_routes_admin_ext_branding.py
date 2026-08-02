from io import BytesIO
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from sharewarez.models import User
from sharewarez.routes_admin_ext.branding import _validate_logo


@pytest.fixture
def branding_admin(db_session):
    unique = uuid4().hex[:8]
    user = User(
        user_id=str(uuid4()),
        name=f'BrandAdmin_{unique}',
        email=f'brand-{unique}@test.invalid',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_branding_requires_login(client):
    response = client.get('/admin/branding')
    assert response.status_code == 302


def test_branding_page_renders_for_admin(client, branding_admin):
    with client.session_transaction() as session:
        session['_user_id'] = str(branding_admin.id)
        session['_fresh'] = True
    response = client.get('/admin/branding')
    assert response.status_code == 200
    assert b'Product branding' in response.data
    assert b'Save branding' in response.data


@pytest.mark.parametrize(
    ('filename', 'content', 'extension'),
    [
        ('logo.png', b'\x89PNG\r\n\x1a\ncontent', '.png'),
        ('logo.jpg', b'\xff\xd8\xffcontent', '.jpg'),
        ('logo.webp', b'RIFF1234WEBPcontent', '.webp'),
    ],
)
def test_logo_validation_accepts_supported_images(filename, content, extension):
    upload = FileStorage(stream=BytesIO(content), filename=filename)
    assert _validate_logo(upload) == extension


def test_logo_validation_rejects_mismatched_content():
    upload = FileStorage(stream=BytesIO(b'not an image'), filename='logo.png')
    with pytest.raises(ValueError, match='does not match'):
        _validate_logo(upload)

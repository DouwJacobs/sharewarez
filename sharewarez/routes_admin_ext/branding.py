from pathlib import Path
from uuid import uuid4

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from sharewarez import cache, db
from sharewarez.models import GlobalSettings
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from . import admin2_bp


DEFAULT_TITLE = 'SharewareZ'
DEFAULT_LOGO = 'newstyle/sharewarez_logo.png'
MAX_LOGO_SIZE = 5 * 1024 * 1024
IMAGE_SIGNATURES = {
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.webp': (b'RIFF',),
}


def _get_or_create_settings():
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    if not settings:
        settings = GlobalSettings(settings={})
        db.session.add(settings)
    return settings


def _validate_logo(upload):
    if not upload or not upload.filename:
        return None
    extension = Path(upload.filename).suffix.lower()
    if extension not in IMAGE_SIGNATURES:
        raise ValueError('Logo must be a PNG, WebP, or JPEG image.')
    upload.seek(0, 2)
    size = upload.tell()
    upload.seek(0)
    if size == 0 or size > MAX_LOGO_SIZE:
        raise ValueError('Logo must be a non-empty image no larger than 5 MB.')
    header = upload.read(12)
    upload.seek(0)
    if not any(header.startswith(signature) for signature in IMAGE_SIGNATURES[extension]):
        raise ValueError('The uploaded file does not match its image format.')
    if extension == '.webp' and header[8:12] != b'WEBP':
        raise ValueError('The uploaded file is not a valid WebP image.')
    return extension


@admin2_bp.route('/admin/branding', methods=['GET', 'POST'])
@login_required
@admin_required
def branding():
    settings_record = _get_or_create_settings()
    saved = dict(settings_record.settings or {})

    if request.method == 'POST':
        try:
            title = request.form.get('site_title', '').strip()
            if not title:
                raise ValueError('Site title is required.')
            if len(title) > 60:
                raise ValueError('Site title must be 60 characters or fewer.')
            if any(ord(character) < 32 for character in title):
                raise ValueError('Site title cannot contain control characters.')

            logo = request.files.get('brand_logo')
            extension = _validate_logo(logo)
            old_logo = saved.get('brandLogoPath')
            if request.form.get('reset_logo') == '1':
                saved['brandLogoPath'] = DEFAULT_LOGO
            elif extension:
                branding_dir = Path(current_app.static_folder) / 'library' / 'branding'
                branding_dir.mkdir(parents=True, exist_ok=True)
                filename = f'logo-{uuid4().hex}{extension}'
                logo.save(branding_dir / filename)
                saved['brandLogoPath'] = f'library/branding/{filename}'

            saved['siteTitle'] = title
            settings_record.settings = saved
            db.session.commit()
            cache.clear()

            new_logo = saved.get('brandLogoPath', DEFAULT_LOGO)
            if old_logo and old_logo != new_logo and old_logo.startswith('library/branding/'):
                old_path = Path(current_app.static_folder) / old_logo
                try:
                    old_path.unlink(missing_ok=True)
                except OSError:
                    current_app.logger.warning('Unable to remove superseded branding image: %s', old_path)

            log_system_event(
                f"Branding updated by {current_user.name}",
                event_type='audit',
                event_level='information',
            )
            flash('Branding updated successfully.', 'success')
            return redirect(url_for('admin2.branding'))
        except ValueError as error:
            flash(str(error), 'error')
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Unable to update branding')
            flash('Branding could not be updated. Please try again.', 'error')

    return render_template(
        'admin/admin_branding.html',
        branding_title=saved.get('siteTitle', DEFAULT_TITLE),
        branding_logo=saved.get('brandLogoPath', DEFAULT_LOGO),
        default_logo=DEFAULT_LOGO,
    )

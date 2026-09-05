from flask import render_template, request, redirect, url_for, flash, current_app, send_file
from flask_login import login_required, current_user
from sharewarez.utils.auth import admin_required
from sharewarez.forms import ThemeUploadForm
from sharewarez.utils.themes import ThemeManager
from sharewarez.utils.event_logging import log_system_event
from sharewarez import db
from sharewarez.models import GlobalSettings
from sqlalchemy import select
import os
import shutil
from pathlib import Path
from typing import Optional, Union
from datetime import datetime, timezone
from . import admin2_bp

# Configuration constants
MAX_THEME_FILE_SIZE = 25 * 1024 * 1024  # 25MB in bytes
ZIP_MAGIC_BYTES = [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08']  # Standard ZIP file signatures
WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}

def validate_theme_file(file) -> tuple[bool, Optional[str]]:
    """Validate uploaded theme file for security and format requirements.
    
    Args:
        file: Uploaded file object from form
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not file or not file.filename:
        return False, "No file provided"
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning
    
    if file_size > MAX_THEME_FILE_SIZE:
        return False, f"File size ({file_size / (1024*1024):.1f}MB) exceeds maximum allowed size (25MB)"
    
    if file_size == 0:
        return False, "File is empty"
    
    # Check magic bytes for ZIP file
    file_header = file.read(4)
    file.seek(0)  # Reset to beginning
    
    if not any(file_header.startswith(magic) for magic in ZIP_MAGIC_BYTES):
        return False, "File is not a valid ZIP archive"
    
    return True, None


def is_valid_theme_name(name: str) -> tuple[bool, Optional[str]]:
    """Check if theme name is valid and safe to use.
    
    Args:
        name: Theme name to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Theme name cannot be empty"
    
    # Check for Windows reserved names
    name_upper = name.upper()
    if name_upper in WINDOWS_RESERVED_NAMES:
        return False, f"'{name}' is a reserved system name and cannot be used"
    
    # Check for reserved names with extensions
    if '.' in name_upper:
        base_name = name_upper.split('.')[0]
        if base_name in WINDOWS_RESERVED_NAMES:
            return False, f"'{name}' uses a reserved system name and cannot be used"
    
    # Check for dangerous characters
    dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
    if any(char in name for char in dangerous_chars):
        return False, f"Theme name contains invalid characters: {', '.join(char for char in dangerous_chars if char in name)}"
    
    # Check for path traversal attempts  
    if '..' in name or (name.startswith('.') and name != '.') or name.endswith('.'):
        return False, "Theme name contains invalid path elements"
    
    return True, None


@admin2_bp.route('/admin/themes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_themes():
    """Manage themes - upload, list, and configure themes.
    
    Returns:
        Response: Rendered template or redirect
    """
    form = ThemeUploadForm()
    theme_manager = ThemeManager(current_app)
    upload_folder = Path(current_app.config['UPLOAD_FOLDER']) / 'themes'
    
    if not upload_folder.exists():
        try:
            upload_folder.mkdir(parents=True, exist_ok=True)
            log_system_event(
                f"Created themes upload directory: {upload_folder}",
                event_type='themes',
                event_level='information'
            )
        except Exception as e:
            log_system_event(
                f"Error creating upload directory: {e}",
                event_type='themes',
                event_level='error'
            )
            flash("Error processing request. Please try again.", 'error')
            return redirect(url_for('admin2.manage_themes'))

    if form.validate_on_submit():
        theme_zip = form.theme_zip.data
        
        # Validate the uploaded file
        is_valid_file, file_error = validate_theme_file(theme_zip)
        if not is_valid_file:
            log_system_event(
                f"Theme upload failed - file validation: {file_error}",
                event_type='themes',
                event_level='warning'
            )
            flash(f"Upload failed: {file_error}", 'error')
            return redirect(url_for('admin2.manage_themes'))
        
        try:
            theme_data = theme_manager.upload_theme(theme_zip)
            if theme_data:
                # Validate theme name
                is_valid_name, name_error = is_valid_theme_name(theme_data.get('name', ''))
                if not is_valid_name:
                    log_system_event(
                        f"Theme upload failed - invalid name '{theme_data.get('name', '')}': {name_error}",
                        event_type='themes',
                        event_level='warning'
                    )
                    flash(f"Upload failed: {name_error}", 'error')
                    return redirect(url_for('admin2.manage_themes'))
                
                log_system_event(
                    f"Theme '{theme_data['name']}' uploaded successfully by admin",
                    event_type='themes',
                    event_level='information'
                )
                flash(f"Theme '{theme_data['name']}' uploaded successfully!", 'success')
            else:
                log_system_event(
                    "Theme upload failed - no theme data returned",
                    event_type='themes',
                    event_level='error'
                )
                flash("Theme upload failed. Please check the error messages.", 'error')
        except ValueError as e:
            log_system_event(
                f"Theme upload failed with ValueError: {e}",
                event_type='themes',
                event_level='warning'
            )
            flash(str(e), 'error')
        except Exception as e:
            log_system_event(
                f"Theme upload failed with unexpected error: {e}",
                event_type='themes',
                event_level='error'
            )
            flash(f"An unexpected error occurred: {str(e)}", 'error')
        return redirect(url_for('admin2.manage_themes'))

    installed_themes = theme_manager.get_installed_themes()
    default_theme = theme_manager.get_default_theme()
    from sharewarez.utils.themes import get_site_default_theme_id
    site_default_theme_id = get_site_default_theme_id(current_app)
    return render_template(
        'admin/admin_manage_themes.html',
        form=form,
        themes=installed_themes,
        default_theme=default_theme,
        site_default_theme_id=site_default_theme_id,
    )


@admin2_bp.route('/admin/themes/site-default', methods=['POST'])
@login_required
@admin_required
def set_site_default_theme():
    """Set the theme inherited by guests and users without an override."""
    theme_id = request.form.get('theme_id', '').strip()
    manager = ThemeManager(current_app)
    theme = manager.get_theme(theme_id)
    if not theme:
        flash('Select an installed theme.', 'error')
        return redirect(url_for('admin2.manage_themes'))

    settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    if not settings_record:
        settings_record = GlobalSettings(settings={})
        db.session.add(settings_record)
    settings = dict(settings_record.settings or {})
    settings['defaultTheme'] = theme_id
    settings_record.settings = settings
    settings_record.last_updated = datetime.now(timezone.utc)
    db.session.commit()
    log_system_event(
        f"Site default theme changed to '{theme.get('name', theme_id)}' by admin {current_user.name}",
        event_type='themes',
        event_level='information',
    )
    flash(f"'{theme.get('name', theme_id)}' is now the site default theme.", 'success')
    return redirect(url_for('admin2.manage_themes'))

@admin2_bp.route('/admin/themes/readme')
@login_required
@admin_required
def theme_readme():
    """Display theme documentation and readme information.
    
    Returns:
        Response: Rendered template with theme documentation
    """
    return render_template('admin/admin_manage_themes_readme.html')


@admin2_bp.route('/admin/themes/builder', defaults={'theme_id': None}, methods=['GET', 'POST'])
@admin2_bp.route('/admin/themes/builder/<theme_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def theme_builder(theme_id):
    """Create or edit themes using a safe visual palette builder."""
    manager = ThemeManager(current_app)
    existing = manager.get_theme(theme_id) if theme_id else None
    if theme_id and (not existing or existing.get('source') != 'builder'):
        flash('Only themes created in the visual builder can be edited.', 'error')
        return redirect(url_for('admin2.manage_themes'))

    defaults = {
        'name': '',
        'description': '',
        'accent': '#557cf4',
        'accent_soft': '#9ab1ff',
        'background': '#0a0b14',
        'sidebar': '#12131f',
        'card': '#12121c',
        'panel': '#181925',
        'text_primary': '#f5f7ff',
        'text_secondary': '#c5ccdc'
    }
    if existing:
        defaults.update(existing.get('palette', {}))
        defaults['name'] = existing.get('name', '')
        defaults['description'] = existing.get('description', '')

    if request.method == 'POST':
        values = {key: request.form.get(key, '').strip() for key in defaults}
        values['author'] = current_user.name
        try:
            saved_id, metadata = manager.save_builder_theme(values, theme_id=theme_id)
            action = 'updated' if theme_id else 'created'
            log_system_event(
                f"Theme '{metadata['name']}' {action} in visual builder by admin",
                event_type='themes',
                event_level='information'
            )
            flash(f"Theme '{metadata['name']}' {action} successfully.", 'success')
            return redirect(url_for('admin2.manage_themes'))
        except ValueError as error:
            defaults.update(values)
            flash(str(error), 'error')

    return render_template(
        'admin/admin_theme_builder.html',
        theme=defaults,
        theme_id=theme_id,
        editing=bool(theme_id)
    )


@admin2_bp.route('/admin/themes/default/download')
@login_required
@admin_required
def download_default_theme():
    """Download the bundled default theme as an upload-compatible ZIP."""
    source = Path(current_app.root_path) / 'setup' / 'default_theme'
    try:
        archive = ThemeManager.create_theme_archive(source)
        log_system_event(
            "Default theme reference downloaded by admin",
            event_type='themes',
            event_level='information'
        )
        return send_file(
            archive,
            mimetype='application/zip',
            as_attachment=True,
            download_name='default-theme-reference.zip'
        )
    except (OSError, ValueError) as error:
        log_system_event(
            f"Default theme download failed: {error}",
            event_type='themes',
            event_level='error'
        )
        flash('The default theme package could not be created.', 'error')
        return redirect(url_for('admin2.manage_themes'))

@admin2_bp.route('/admin/themes/delete/<theme_name>', methods=['POST'])
@login_required
@admin_required
def delete_theme(theme_name: str):
    """Delete a theme from the system.
    
    Args:
        theme_name: Name of the theme to delete
        
    Returns:
        Response: Redirect to themes management page
    """
    theme_manager = ThemeManager(current_app)
    
    # Validate theme name before deletion
    is_valid_name, name_error = is_valid_theme_name(theme_name)
    if not is_valid_name:
        log_system_event(
            f"Theme deletion failed - invalid name '{theme_name}': {name_error}",
            event_type='themes',
            event_level='warning'
        )
        flash(f"Deletion failed: {name_error}", 'error')
        return redirect(url_for('admin2.manage_themes'))
    
    try:
        theme_manager.delete_themefile(theme_name)
        log_system_event(
            f"Theme '{theme_name}' deleted successfully by admin",
            event_type='themes',
            event_level='information'
        )
        flash(f"Theme '{theme_name}' deleted successfully!", 'success')
    except ValueError as e:
        log_system_event(
            f"Theme deletion failed with ValueError: {e}",
            event_type='themes',
            event_level='warning'
        )
        flash(str(e), 'error')
    except Exception as e:
        log_system_event(
            f"Theme deletion failed with unexpected error: {e}",
            event_type='themes',
            event_level='error'
        )
        flash(f"An unexpected error occurred: {str(e)}", 'error')
    return redirect(url_for('admin2.manage_themes'))

@admin2_bp.route('/admin/themes/reset', methods=['POST'])
@login_required
@admin_required
def reset_default_themes():
    """Restore packaged themes without destroying the working copy on failure."""
    from sharewarez.utils.theme_install import install_packaged_themes

    source = current_app.config.get('THEME_SOURCE_ROOT', Path(current_app.root_path) / 'setup')
    target = current_app.config.get(
        'THEME_INSTALL_ROOT', Path(current_app.static_folder) / 'library' / 'themes'
    )
    try:
        install_packaged_themes(source, target)
        flash('Bundled themes have been restored successfully!', 'success')
        log_system_event('Packaged themes restored', event_type='themes', event_level='information')
    except Exception as error:
        flash('Theme reset failed; the prior themes were retained unless recovery is reported in the log.', 'error')
        log_system_event(f'Theme reset failed: {error}', event_type='themes', event_level='error')
    return redirect(url_for('admin2.manage_themes'))

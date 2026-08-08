import os
import json
import zipfile
import shutil
import re
from datetime import date
from io import BytesIO
from flask import current_app, flash, g, has_request_context
from werkzeug.utils import secure_filename
from sharewarez.models import GlobalSettings, UserPreference
from sharewarez import db
from sqlalchemy import select, update

SITE_DEFAULT_THEME_VALUE = '__site_default__'


def get_site_default_theme_id(app=None):
    """Return a valid installed theme selected as the site-wide default."""
    cache_key = '_site_default_theme_id'
    if has_request_context() and hasattr(g, cache_key):
        return getattr(g, cache_key)

    settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
    configured = (settings_record.settings or {}).get('defaultTheme', 'default') if settings_record else 'default'
    manager = ThemeManager(app or current_app)
    theme_id = configured if manager.get_theme(configured) else 'default'
    if has_request_context():
        setattr(g, cache_key, theme_id)
    return theme_id


def resolve_theme_id(user=None, app=None):
    """Resolve a user override, otherwise falling back to the site default."""
    selected = None
    if user is not None and getattr(user, 'is_authenticated', False):
        preferences = getattr(user, 'preferences', None)
        selected = getattr(preferences, 'theme', None) if preferences else None

    manager = ThemeManager(app or current_app)
    if selected:
        if manager.get_theme(selected):
            return selected
        # Older preferences sometimes stored a display name.
        matched = next(
            (theme['id'] for theme in manager.get_installed_themes() if theme['name'] == selected),
            None,
        )
        if matched:
            return matched
    return get_site_default_theme_id(app)

class ThemeManager:
    def __init__(self, app):
        self.app = app
        self.theme_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static/library/themes')

    def get_default_theme(self):
        default_theme_path = os.path.join(self.theme_folder, 'default', 'theme.json')
        try:
            with open(default_theme_path, 'r') as json_file:
                return json.load(json_file)
        except Exception as e:
            print(f"Error reading default theme: {str(e)}")
            return None

    def get_installed_themes(self):
        themes = []
        try:
            theme_names = os.listdir(self.theme_folder)
        except OSError:
            return themes
        for theme_name in theme_names:
            theme_path = os.path.join(self.theme_folder, theme_name)
            if os.path.isdir(theme_path):
                json_path = os.path.join(theme_path, 'theme.json')
                if os.path.exists(json_path):
                    try:
                        with open(json_path, 'r') as json_file:
                            theme_data = json.load(json_file)
                            themes.append({
                                'id': theme_name,
                                'name': theme_data.get('name', theme_name),
                                'author': theme_data.get('author', 'Unknown'),
                                'release_date': theme_data.get('release_date', 'Unknown'),
                                'description': theme_data.get('description', 'No description available'),
                                'bundled': theme_name == 'default' or bool(theme_data.get('bundled', False)),
                                'source': ('default' if theme_name == 'default' else
                                           theme_data.get('source', 'bundled' if theme_data.get('bundled') else 'uploaded')),
                                'editable': theme_data.get('source') == 'builder'
                            })
                    except Exception as e:
                        print(f"Error reading theme {theme_name}: {str(e)}")
        return sorted(themes, key=lambda theme: (theme['id'] != 'default', theme['name'].lower()))

    def get_theme(self, theme_id):
        """Return metadata for one safely resolved installed theme."""
        safe_id = secure_filename(theme_id)
        if not safe_id or safe_id != theme_id:
            return None
        path = os.path.join(self.theme_folder, safe_id, 'theme.json')
        try:
            with open(path, 'r') as json_file:
                data = json.load(json_file)
            data['id'] = safe_id
            return data
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _validate_builder_color(value):
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError('Theme colors must use the #RRGGBB format.')
        return value.lower()

    @staticmethod
    def _rgb(value):
        value = value.lstrip('#')
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))

    def save_builder_theme(self, data, theme_id=None):
        """Create or update a theme produced by the visual builder."""
        name = str(data.get('name', '')).strip()
        description = str(data.get('description', '')).strip()
        if not name or len(name) > 60:
            raise ValueError('Theme name must be between 1 and 60 characters.')
        if not description or len(description) > 240:
            raise ValueError('Description must be between 1 and 240 characters.')

        palette = {
            key: self._validate_builder_color(data.get(key))
            for key in (
                'accent', 'accent_soft', 'background', 'sidebar', 'card', 'panel',
                'text_primary', 'text_secondary'
            )
        }
        target_id = secure_filename(name) if theme_id is None else secure_filename(theme_id)
        if not target_id or target_id in ('default', 'Default'):
            raise ValueError('Choose a different theme name.')
        target = os.path.join(self.theme_folder, target_id)

        if theme_id is None and os.path.exists(target):
            raise ValueError(f"A theme named '{name}' already exists.")
        if theme_id is not None:
            existing = self.get_theme(target_id)
            if not existing or existing.get('source') != 'builder':
                raise ValueError('Only themes created in the visual builder can be edited.')

        os.makedirs(os.path.join(target, 'css'), exist_ok=True)
        metadata = {
            'name': name,
            'author': str(data.get('author') or 'Administrator'),
            'description': description,
            'version': '1.0.0',
            'release_date': date.today().isoformat(),
            'source': 'builder',
            'palette': palette
        }
        with open(os.path.join(target, 'theme.json'), 'w') as json_file:
            json.dump(metadata, json_file, indent=2)
            json_file.write('\n')

        accent = self._rgb(palette['accent'])
        soft = self._rgb(palette['accent_soft'])
        css = f""":root {{
    --theme-accent-rgb: {accent[0]}, {accent[1]}, {accent[2]};
    --theme-accent-soft-rgb: {soft[0]}, {soft[1]}, {soft[2]};
    --theme-sidebar-top: {palette['sidebar']};
    --theme-sidebar-bottom: color-mix(in srgb, {palette['sidebar']} 72%, black);
    --theme-card-top: {palette['card']};
    --theme-card-bottom: color-mix(in srgb, {palette['card']} 74%, black);
    --theme-panel-bg: color-mix(in srgb, {palette['panel']} 94%, transparent);
    --theme-text-primary: {palette['text_primary']};
    --theme-text-secondary: {palette['text_secondary']};
    --text-white: var(--theme-text-primary);
    --text-light: var(--theme-text-secondary);
    --text-muted: color-mix(in srgb, var(--theme-text-secondary) 72%, transparent);
    --text-muted-light: color-mix(in srgb, var(--theme-text-secondary) 84%, transparent);
    --bs-body-color: var(--theme-text-primary);
    --bs-secondary-color: var(--theme-text-secondary);
    --btn-primary: {palette['accent']};
    --btn-primary-hover: {palette['accent_soft']};
    --form-focus-border: {palette['accent_soft']};
}}

body {{
    background-color: {palette['background']};
    background-image: radial-gradient(circle at 75% 0%, rgba({accent[0]}, {accent[1]}, {accent[2]}, .12), transparent 35%);
}}
a {{ color: {palette['accent_soft']}; }}
"""
        with open(os.path.join(target, 'css', 'theme-overrides.css'), 'w') as css_file:
            css_file.write(css)
        return target_id, metadata

    @staticmethod
    def create_theme_archive(theme_path):
        """Create an upload-compatible ZIP archive from a theme directory."""
        theme_path = os.path.realpath(theme_path)
        if not os.path.isfile(os.path.join(theme_path, 'theme.json')):
            raise ValueError('Theme source does not contain theme.json.')
        if not os.path.isdir(os.path.join(theme_path, 'css')):
            raise ValueError('Theme source does not contain a css directory.')

        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
            for root, dirs, files in os.walk(theme_path):
                dirs[:] = sorted(directory for directory in dirs if not directory.startswith('.'))
                for filename in sorted(files):
                    if filename.startswith('.'):
                        continue
                    source = os.path.join(root, filename)
                    if os.path.islink(source):
                        continue
                    zip_file.write(source, os.path.relpath(source, theme_path))
        archive.seek(0)
        return archive

    def upload_theme(self, theme_zip):
        if not os.path.exists(self.app.config['UPLOAD_FOLDER']):
            flash('Error: Library folder does not exist.', 'error')
            return None

        if not os.path.exists(self.theme_folder):
            try:
                os.makedirs(self.theme_folder)
                flash('Themes folder created successfully.', 'info')
            except Exception as e:
                flash(f'Error creating themes folder: {str(e)}', 'error')
                return None

        temp_dir = os.path.join(self.app.config['UPLOAD_FOLDER'], 'temp_theme')
        os.makedirs(temp_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(theme_zip, 'r') as zip_ref:
                temp_dir_real = os.path.realpath(temp_dir)
                for member in zip_ref.infolist():
                    # Reject absolute paths, drive letters, and any traversal
                    member_name = member.filename
                    if member_name.startswith(('/', '\\')) or (len(member_name) > 1 and member_name[1] == ':'):
                        raise ValueError(f"Unsafe absolute path in zip: {member_name}")
                    target_path = os.path.realpath(os.path.join(temp_dir, member_name))
                    if target_path != temp_dir_real and not target_path.startswith(temp_dir_real + os.sep):
                        raise ValueError(f"Unsafe path in zip (traversal): {member_name}")
                    # Reject symlinks/hardlinks and other non-regular entries
                    mode = member.external_attr >> 16
                    if mode and (mode & 0o170000) not in (0o040000, 0o100000, 0):
                        raise ValueError(f"Unsafe entry type in zip: {member_name}")
                zip_ref.extractall(temp_dir)

            theme_json_path = os.path.join(temp_dir, 'theme.json')
            if not os.path.exists(theme_json_path):
                raise ValueError("theme.json not found in the uploaded zip file")

            with open(theme_json_path, 'r') as json_file:
                theme_data = json.load(json_file)

            required_fields = ['name', 'description', 'author', 'release_date']
            for field in required_fields:
                if field not in theme_data:
                    raise ValueError(f"Missing required field '{field}' in theme.json")

            css_folder = os.path.join(temp_dir, 'css')
            if not os.path.exists(css_folder):
                raise ValueError("CSS folder not found in the uploaded theme")

            theme_name = secure_filename(theme_data['name'])
            theme_path = os.path.join(self.theme_folder, theme_name)
            if os.path.exists(theme_path):
                raise ValueError(f"Theme '{theme_name}' already exists")

            theme_data['source'] = 'uploaded'
            with open(theme_json_path, 'w') as json_file:
                json.dump(theme_data, json_file, indent=2)
                json_file.write('\n')

            shutil.move(temp_dir, theme_path)
            flash(f'Theme "{theme_data["name"]}" uploaded successfully.', 'success')
            return theme_data
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            flash(f'Error: Invalid zip file - {str(e)}', 'error')
            print(f"Zip file error during theme upload: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            flash('Error: Invalid theme.json file - not valid JSON.', 'error')
            print(f"JSON decode error in theme upload: {str(e)}")
            return None
        except ValueError as e:
            flash(f'Error: {str(e)}', 'error')
            print(f"Validation error during theme upload: {str(e)}")
            return None
        except (OSError, IOError) as e:
            flash(f'Error: File system error - {str(e)}', 'error')
            print(f"File system error during theme upload: {str(e)}")
            return None
        except Exception as e:
            flash(f'Error: Unexpected error during theme upload - {str(e)}', 'error')
            print(f"Unexpected error during theme upload: {str(e)}")
            return None
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def validate_theme_structure(self, theme_path):
        required_folders = ['css']
        return all(os.path.exists(os.path.join(theme_path, folder)) for folder in required_folders)

    def delete_themefile(self, theme_name):
        if theme_name in ('Default', 'default'):
            raise ValueError("Cannot delete the default theme.")
        theme_path = os.path.join(self.theme_folder, secure_filename(theme_name))
        if not os.path.exists(theme_path):
            raise ValueError(f"Theme '{theme_name}' does not exist.")

        json_path = os.path.join(theme_path, 'theme.json')
        try:
            with open(json_path, 'r') as json_file:
                theme_data = json.load(json_file)
        except (OSError, json.JSONDecodeError):
            theme_data = {}
        if secure_filename(theme_name) == 'default' or theme_data.get('bundled', False):
            raise ValueError("Bundled themes cannot be deleted.")

        try:
            shutil.rmtree(theme_path)
        except Exception as e:
            raise Exception(f"Error deleting theme: {str(e)}")

        display_name = theme_data.get('name')
        values = [theme_name]
        if display_name:
            values.append(display_name)
        db.session.execute(update(UserPreference).where(UserPreference.theme.in_(values)).values(theme='default'))
        settings_record = db.session.execute(select(GlobalSettings)).scalars().first()
        if settings_record and (settings_record.settings or {}).get('defaultTheme') in values:
            settings = dict(settings_record.settings or {})
            settings['defaultTheme'] = 'default'
            settings_record.settings = settings
        db.session.commit()

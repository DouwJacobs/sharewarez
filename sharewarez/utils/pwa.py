import hashlib
import re
from io import BytesIO
from pathlib import Path

from flask import current_app
from PIL import Image

from sharewarez import app_version
from sharewarez.utils.processors import get_global_settings
from sharewarez.utils.themes import ThemeManager, get_site_default_theme_id


DEFAULT_THEME_COLOR = '#2563eb'
DEFAULT_BACKGROUND_COLOR = '#0a0a0f'
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def _valid_color(value, fallback):
    return value.lower() if isinstance(value, str) and HEX_COLOR.fullmatch(value) else fallback


def _theme_css_colors(theme_id):
    css_path = Path(current_app.root_path) / 'static' / 'library' / 'themes' / theme_id / 'css' / 'theme-overrides.css'
    try:
        css = css_path.read_text(encoding='utf-8')
    except OSError:
        return None, None
    accent_match = re.search(r'--btn-primary\s*:\s*(#[0-9a-fA-F]{6})', css)
    background_match = re.search(r'body\s*\{[^}]*background-color\s*:\s*(#[0-9a-fA-F]{6})', css, re.DOTALL)
    return (
        accent_match.group(1) if accent_match else None,
        background_match.group(1) if background_match else None,
    )


def get_pwa_branding():
    settings = get_global_settings()
    theme_id = get_site_default_theme_id(current_app)
    theme = ThemeManager(current_app).get_theme(theme_id) or {}
    palette = theme.get('palette') or {}
    css_accent, css_background = _theme_css_colors(theme_id)
    theme_color = _valid_color(palette.get('accent') or css_accent, DEFAULT_THEME_COLOR)
    background_color = _valid_color(palette.get('background') or css_background, DEFAULT_BACKGROUND_COLOR)
    logo_path = settings['brand_logo_path']
    logo_file = Path(current_app.static_folder) / logo_path
    try:
        logo_mtime = logo_file.stat().st_mtime_ns
    except OSError:
        logo_mtime = 0
    identity = '|'.join((
        settings['site_title'], logo_path, theme_id, theme_color,
        background_color, str(logo_mtime), app_version,
    ))
    return {
        'site_title': settings['site_title'],
        'short_name': settings['site_title'][:30],
        'logo_path': logo_path,
        'theme_id': theme_id,
        'theme_color': theme_color,
        'background_color': background_color,
        'revision': hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16],
    }


def render_pwa_icon(size, maskable=False):
    if size not in (192, 512):
        raise ValueError('Unsupported PWA icon size.')
    branding = get_pwa_branding()
    static_root = Path(current_app.static_folder).resolve()
    logo_path = (static_root / branding['logo_path']).resolve()
    if static_root not in logo_path.parents or not logo_path.is_file():
        logo_path = static_root / 'newstyle' / 'sharewarez_logo.png'

    with Image.open(logo_path) as source:
        logo = source.convert('RGBA')
        safe_ratio = 0.60 if maskable else 0.86
        maximum = max(1, round(size * safe_ratio))
        logo.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
        background = branding['background_color'] if maskable else (0, 0, 0, 0)
        canvas = Image.new('RGBA', (size, size), background)
        position = ((size - logo.width) // 2, (size - logo.height) // 2)
        canvas.alpha_composite(logo, position)
        output = BytesIO()
        canvas.save(output, format='PNG', optimize=True)
    output.seek(0)
    return output, branding

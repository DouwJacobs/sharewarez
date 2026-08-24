"""Consistent, human-friendly presentation helpers for templates."""

from datetime import date, datetime, timezone


def _parse_temporal(value):
    if isinstance(value, (date, datetime)):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return value
    return value


def _format_calendar_date(value):
    return f'{value.day} {value:%b %Y}'


def friendly_datetime(value):
    if not value:
        return 'Not available'
    value = _parse_temporal(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return _format_calendar_date(value)
    if not isinstance(value, datetime):
        return str(value)
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    seconds = max(0, int((now - aware.astimezone(timezone.utc)).total_seconds()))
    if seconds < 60:
        return 'Just now'
    if seconds < 3600:
        minutes = seconds // 60
        return f'{minutes} minute' + ('' if minutes == 1 else 's') + ' ago'
    if seconds < 86400:
        hours = seconds // 3600
        return f'{hours} hour' + ('' if hours == 1 else 's') + ' ago'
    if seconds < 604800:
        days = seconds // 86400
        return f'{days} day' + ('' if days == 1 else 's') + ' ago'
    return f'{_format_calendar_date(aware)}, {aware:%H:%M}'


def friendly_date(value):
    if not value:
        return 'Not available'
    value = _parse_temporal(value)
    if isinstance(value, (date, datetime)):
        return _format_calendar_date(value)
    return str(value)

from sharewarez import db
from sharewarez.models import SystemEvents
from datetime import datetime, timezone
from typing import Optional, Union
from flask import current_app, has_app_context
from flask_login import current_user


LEVEL_ALIASES = {
    'info': 'information',
    'informational': 'information',
    'warn': 'warning',
}

def log_system_event(
    event_text: str,
    event_type: str = 'log',
    event_level: str = 'information',
    audit_user: Optional[Union[int, str]] = None
) -> bool:
    """
    Log a system event to the database.
    
    Args:
        event_text (str): The message to log (required, max 256 chars)
        event_type (str, optional): Type of event (default: 'log', max 32 chars)
        event_level (str, optional): Level of event (default: 'information', max 32 chars)
        audit_user (Union[int, str], optional): User ID or 'system' for system events
            If None, attempts to get current_user.id, falls back to 'system'
    
    Returns:
        bool: True if logging was successful, False otherwise
    """
    try:
        event_text = str(event_text or '').strip() or 'No event details provided'
        event_type = str(event_type or 'log').strip().lower().replace(' ', '_') or 'log'
        event_level = str(event_level or 'information').strip().lower() or 'information'
        event_level = LEVEL_ALIASES.get(event_level, event_level)

        # Keep values within the current schema limits.
        event_text = event_text[:256]
        event_type = event_type[:32]
        event_level = event_level[:32]
        
        # Handle audit_user logic
        if audit_user is None:
            # Try to get current user ID, fall back to 'system'
            audit_user = getattr(current_user, 'id', None)
        
        # Create new system event
        new_event = SystemEvents(
            event_text=event_text,
            event_type=event_type,
            event_level=event_level,
            audit_user=audit_user if audit_user != 'system' else None,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Add and commit to database
        db.session.add(new_event)
        db.session.commit()
        
        return True
        
    except Exception as e:
        db.session.rollback()
        print(f"Error logging system event: {str(e)}")
        if has_app_context():
            current_app.logger.error('Unable to persist system event: %s', e)
        return False

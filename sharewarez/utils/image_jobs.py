"""Durable artwork discovery requests, independent of web-process lifetime."""
from sharewarez.utils.background_jobs import enqueue


def enqueue_image_refresh(
    game_uuid, *, replace_existing=False, expected_igdb_id=None,
    audit_user_id=None, refresh_reason='background', commit=True,
):
    return enqueue(
        'game.refresh_images',
        {
            'game_uuid': game_uuid,
            'replace_existing': bool(replace_existing),
            'expected_igdb_id': expected_igdb_id,
            'audit_user_id': audit_user_id,
            'refresh_reason': refresh_reason,
        },
        queue='images', created_by_id=audit_user_id, commit=commit,
    )

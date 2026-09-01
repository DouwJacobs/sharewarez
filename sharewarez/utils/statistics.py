from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sharewarez.models import (
    DownloadRequest, DownloadTransfer, Game, User, user_favorites, InviteToken,
)
from sharewarez import db

def get_download_statistics():
    """Gather various download statistics"""
    
    completed = DownloadTransfer.status == 'completed'

    # Completed HTTP deliveries per user. Reusable link creation is not a download.
    downloads_per_user = db.session.execute(
        select(User.name, func.count(DownloadTransfer.id).label('download_count'))
        .join(DownloadTransfer, DownloadTransfer.user_id == User.id)
        .where(completed)
        .group_by(User.id)
        .order_by(func.count(DownloadTransfer.id).desc())
    ).all()

    transfer_game_uuid = func.coalesce(
        DownloadTransfer.game_uuid, DownloadRequest.game_uuid,
    )
    top_games = db.session.execute(
        select(Game.name, func.count(DownloadTransfer.id))
        .select_from(DownloadTransfer)
        .outerjoin(DownloadRequest, DownloadRequest.id == DownloadTransfer.download_request_id)
        .join(Game, Game.uuid == transfer_game_uuid)
        .where(completed)
        .group_by(Game.id)
        .order_by(func.count(DownloadTransfer.id).desc())
        .limit(10)
    ).all()

    # Completed transfer trends (last 30 days). Older rows may not have an
    # ended_at value, so retain started_at only as an explicit legacy fallback.
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    completed_at = func.coalesce(DownloadTransfer.ended_at, DownloadTransfer.started_at)
    download_trends = db.session.execute(
        select(func.date(completed_at), func.count(DownloadTransfer.id))
        .where(completed, completed_at >= thirty_days_ago)
        .group_by(func.date(completed_at))
        .order_by(func.date(completed_at))
    ).all()

    transfer_totals = dict(db.session.execute(
        select(DownloadTransfer.status, func.coalesce(func.sum(DownloadTransfer.bytes_sent), 0))
        .group_by(DownloadTransfer.status)
    ).all())

    # Reuse the ordered per-user aggregation instead of running it twice.
    top_downloaders = downloads_per_user[:10]

    # Users with most favorites
    top_collectors = db.session.execute(
        select(User.name, func.count(user_favorites.c.game_uuid).label('favorite_count'))
        .join(user_favorites)
        .group_by(User.id)
        .order_by(func.count(user_favorites.c.game_uuid).desc())
        .limit(10)
    ).all()

    # Users with invite tokens
    users_with_invites = db.session.execute(
        select(User.name, func.count(InviteToken.id).label('invite_count'))
        .join(InviteToken, User.user_id == InviteToken.creator_user_id)
        .group_by(User.id)
        .order_by(func.count(InviteToken.id).desc())
        .limit(10)
    ).all()

    return {
        'users_with_invites': {
            'labels': [user[0] for user in users_with_invites],
            'data': [user[1] for user in users_with_invites]
        },
        'downloads_per_user': {
            'labels': [user[0] for user in downloads_per_user],
            'data': [user[1] for user in downloads_per_user]
        },
        'top_downloaders': {
            'labels': [user[0] for user in top_downloaders],
            'data': [user[1] for user in top_downloaders]
        },
        'top_collectors': {
            'labels': [user[0] for user in top_collectors],
            'data': [user[1] for user in top_collectors]
        },
        'top_games': {
            'labels': [game[0] for game in top_games],
            'data': [game[1] for game in top_games]
        },
        'download_trends': {
            'labels': [trend[0].strftime('%Y-%m-%d') for trend in download_trends],
            'data': [trend[1] for trend in download_trends]
        },
        'transfer_summary': {
            'completed_bytes': int(transfer_totals.get('completed', 0)),
            'interrupted_bytes': int(transfer_totals.get('interrupted', 0)),
            'cancelled_bytes': int(transfer_totals.get('cancelled', 0)),
        },
    }

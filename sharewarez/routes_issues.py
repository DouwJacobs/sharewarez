from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from sharewarez import db
from sharewarez.models import Game, GameIssue, GameIssueComment, GlobalSettings, User
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.issue_notifications import (
    notify_issue_comment,
    notify_issue_created,
    notify_issue_deleted,
    notify_issue_status,
)


issues_bp = Blueprint('issues', __name__)

ISSUE_CATEGORIES = {
    'broken_download': 'Broken or corrupt download',
    'missing_files': 'Missing files',
    'launch_problem': 'Launch or installation problem',
    'metadata': 'Incorrect game information',
    'other': 'Other',
}
ISSUE_STATUSES = {
    'open': 'Open',
    'in_progress': 'In progress',
    'waiting_on_user': 'Waiting on user',
    'resolved': 'Resolved',
    'closed': 'Closed',
}
OPEN_ISSUE_STATUSES = {'open', 'in_progress', 'waiting_on_user'}
CLOSED_ISSUE_STATUSES = {'resolved', 'closed'}

_issue_rate_hits = defaultdict(deque)
_issue_rate_lock = Lock()


def _issues_enabled():
    settings = db.session.execute(select(GlobalSettings)).scalars().first()
    values = settings.settings if settings and isinstance(settings.settings, dict) else {}
    return values.get('enableGameIssues', True)


def _require_enabled():
    if not _issues_enabled():
        abort(404)


def _rate_limited(scope, limit, window_seconds=60):
    key = (scope, current_user.id)
    now = monotonic()
    with _issue_rate_lock:
        hits = _issue_rate_hits[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
            response = jsonify({'error': f'Too many requests. Try again in {retry_after} seconds.'})
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            return response
        hits.append(now)
    return None


def _issue_or_404(issue_id, admin=False):
    options = (
        selectinload(GameIssue.game),
        selectinload(GameIssue.reporter),
        selectinload(GameIssue.handled_by),
        selectinload(GameIssue.comments).selectinload(GameIssueComment.author),
    )
    issue = db.session.execute(
        select(GameIssue).options(*options).where(GameIssue.id == issue_id)
    ).scalar_one_or_none() or abort(404)
    if not admin and issue.reporter_id != current_user.id:
        abort(404)
    return issue


def _validate_issue_payload(data):
    category = str(data.get('category') or '').strip().lower()
    title = str(data.get('title') or '').strip()
    description = str(data.get('description') or '').strip()
    if category not in ISSUE_CATEGORIES:
        raise ValueError('Choose a valid issue category.')
    if not title and description:
        title = description.splitlines()[0][:160]
    if not 5 <= len(title) <= 160:
        raise ValueError('Enter a title between 5 and 160 characters.')
    if not 10 <= len(description) <= 5000:
        raise ValueError('Describe the issue in 10 to 5000 characters.')
    return category, title, description


def _validate_comment(data):
    body = str(data.get('body') or '').strip()
    if not 1 <= len(body) <= 4000:
        raise ValueError('Comments must be between 1 and 4000 characters.')
    return body


def _add_status_activity(issue, author, previous_status):
    activity = GameIssueComment(
        issue=issue,
        author_id=author.id,
        body=(
            f'Status changed from {ISSUE_STATUSES[previous_status]} '
            f'to {ISSUE_STATUSES[issue.status]}.'
        ),
        kind='status',
    )
    db.session.add(activity)
    return activity


def _transition_issue(issue, status, actor):
    if status not in ISSUE_STATUSES:
        raise ValueError('Choose a valid issue status.')
    previous_status = issue.status
    if previous_status == status:
        return None, previous_status
    issue.status = status
    issue.handled_by_user_id = actor.id if actor.role == 'admin' else issue.handled_by_user_id
    issue.resolved_at = datetime.now(timezone.utc) if status in CLOSED_ISSUE_STATUSES else None
    activity = _add_status_activity(issue, actor, previous_status)
    db.session.commit()
    notify_issue_status(issue, previous_status, activity)
    return activity, previous_status


def _group_issues(issues, ordered_game_uuids=None):
    grouped = defaultdict(list)
    for issue in issues:
        grouped[issue.game_uuid].append(issue)
    order = ordered_game_uuids or list(grouped)
    groups = []
    for game_uuid in order:
        records = grouped.get(game_uuid, [])
        if not records:
            continue
        groups.append({
            'game': records[0].game,
            'issues': records,
            'open_count': sum(item.status in OPEN_ISSUE_STATUSES for item in records),
            'closed_count': sum(item.status in CLOSED_ISSUE_STATUSES for item in records),
            'updated_at': max(item.updated_at for item in records),
        })
    return groups


@issues_bp.post('/game_details/<game_uuid>/issues')
@login_required
def create_issue(game_uuid):
    _require_enabled()
    if limited := _rate_limited('create', 8):
        return limited
    game = db.session.execute(select(Game).where(Game.uuid == game_uuid)).scalar_one_or_none() or abort(404)
    data = request.get_json(silent=True) or request.form
    try:
        category, title, description = _validate_issue_payload(data)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    issue = GameIssue(
        game_uuid=game.uuid,
        reporter_id=current_user.id,
        category=category,
        title=title,
        description=description,
    )
    db.session.add(issue)
    db.session.commit()
    log_system_event(
        f'{current_user.name} created issue {issue.id} for {game.name}',
        event_type='game_issue', event_level='information',
    )
    notify_issue_created(issue)
    return jsonify({
        'message': 'Issue submitted. You can follow replies from My Issues.',
        'issue_id': issue.id,
        'url': url_for('issues.issue_detail', issue_id=issue.id),
    }), 201


@issues_bp.get('/issues')
@login_required
def my_issues():
    _require_enabled()
    scope = (request.args.get('status') or 'open').strip()
    conditions = [GameIssue.reporter_id == current_user.id]
    if scope == 'open':
        conditions.append(GameIssue.status.in_(OPEN_ISSUE_STATUSES))
    elif scope == 'closed':
        conditions.append(GameIssue.status.in_(CLOSED_ISSUE_STATUSES))
    elif scope != 'all':
        scope = 'open'
        conditions.append(GameIssue.status.in_(OPEN_ISSUE_STATUSES))
    issues = db.session.execute(
        select(GameIssue)
        .options(
            selectinload(GameIssue.game),
            selectinload(GameIssue.comments),
        )
        .where(*conditions)
        .order_by(GameIssue.updated_at.desc())
    ).scalars().all()
    counts = dict(db.session.execute(
        select(GameIssue.status, func.count(GameIssue.id))
        .where(GameIssue.reporter_id == current_user.id)
        .group_by(GameIssue.status)
    ).all())
    return render_template(
        'issues/my_issues.html', groups=_group_issues(issues), selected_scope=scope,
        status_counts=counts, open_statuses=OPEN_ISSUE_STATUSES,
        closed_statuses=CLOSED_ISSUE_STATUSES, status_labels=ISSUE_STATUSES,
        category_labels=ISSUE_CATEGORIES,
    )


@issues_bp.get('/issues/<int:issue_id>')
@login_required
def issue_detail(issue_id):
    _require_enabled()
    issue = _issue_or_404(issue_id)
    public_comments = [comment for comment in issue.comments if not comment.is_internal]
    return render_template(
        'issues/issue_detail.html', issue=issue, comments=public_comments,
        status_labels=ISSUE_STATUSES, category_labels=ISSUE_CATEGORIES,
    )


@issues_bp.post('/issues/<int:issue_id>/edit')
@login_required
def edit_issue(issue_id):
    _require_enabled()
    issue = _issue_or_404(issue_id)
    if issue.is_closed:
        flash('Closed issues cannot be edited.', 'error')
        return redirect(url_for('issues.issue_detail', issue_id=issue.id))
    try:
        category, title, description = _validate_issue_payload(request.form)
        issue.category = category
        issue.title = title
        issue.description = description
        db.session.commit()
        log_system_event(
            f'{current_user.name} edited issue {issue.id}',
            event_type='game_issue', event_level='information',
        )
        flash('Issue details updated.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('issues.issue_detail', issue_id=issue.id))


@issues_bp.post('/issues/<int:issue_id>/comments')
@login_required
def add_user_comment(issue_id):
    _require_enabled()
    if limited := _rate_limited('comment', 20):
        return limited
    issue = _issue_or_404(issue_id)
    if issue.is_closed:
        flash('Reopen this issue before adding a comment.', 'error')
        return redirect(url_for('issues.issue_detail', issue_id=issue.id))
    try:
        body = _validate_comment(request.form)
        comment = GameIssueComment(issue=issue, author_id=current_user.id, body=body)
        issue.updated_at = datetime.now(timezone.utc)
        db.session.add(comment)
        db.session.commit()
        notify_issue_comment(issue, comment)
        flash('Reply added.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('issues.issue_detail', issue_id=issue.id))


@issues_bp.post('/issues/<int:issue_id>/close')
@login_required
def close_issue(issue_id):
    _require_enabled()
    issue = _issue_or_404(issue_id)
    _transition_issue(issue, 'closed', current_user)
    flash('Issue closed.', 'success')
    return redirect(url_for('issues.issue_detail', issue_id=issue.id))


@issues_bp.post('/issues/<int:issue_id>/reopen')
@login_required
def reopen_issue(issue_id):
    _require_enabled()
    issue = _issue_or_404(issue_id)
    _transition_issue(issue, 'open', current_user)
    flash('Issue reopened.', 'success')
    return redirect(url_for('issues.issue_detail', issue_id=issue.id))


@issues_bp.get('/admin/issues')
@login_required
@admin_required
def admin_issues():
    scope = (request.args.get('status') or 'open').strip()
    category = (request.args.get('category') or '').strip()
    search_term = (request.args.get('q') or '').strip()[:100]
    page = max(request.args.get('page', 1, type=int), 1)
    conditions = []
    if scope == 'open':
        conditions.append(GameIssue.status.in_(OPEN_ISSUE_STATUSES))
    elif scope == 'closed':
        conditions.append(GameIssue.status.in_(CLOSED_ISSUE_STATUSES))
    elif scope != 'all':
        scope = 'open'
        conditions.append(GameIssue.status.in_(OPEN_ISSUE_STATUSES))
    if category in ISSUE_CATEGORIES:
        conditions.append(GameIssue.category == category)
    else:
        category = ''
    if search_term:
        pattern = f'%{search_term}%'
        conditions.append(or_(
            GameIssue.title.ilike(pattern),
            GameIssue.description.ilike(pattern),
            Game.name.ilike(pattern),
            User.name.ilike(pattern),
        ))

    grouped_statement = (
        select(GameIssue.game_uuid, func.max(GameIssue.updated_at).label('last_updated'))
        .join(Game, Game.uuid == GameIssue.game_uuid)
        .join(User, User.id == GameIssue.reporter_id)
        .where(*conditions)
        .group_by(GameIssue.game_uuid)
        .order_by(func.max(GameIssue.updated_at).desc())
    )
    pagination = db.paginate(grouped_statement, page=page, per_page=12, error_out=False)
    game_uuids = list(pagination.items)
    issues = []
    if game_uuids:
        issues = db.session.execute(
            select(GameIssue)
            .join(Game, Game.uuid == GameIssue.game_uuid)
            .join(User, User.id == GameIssue.reporter_id)
            .options(
                selectinload(GameIssue.game),
                selectinload(GameIssue.reporter),
                selectinload(GameIssue.comments),
            )
            .where(GameIssue.game_uuid.in_(game_uuids), *conditions)
            .order_by(GameIssue.updated_at.desc())
        ).scalars().all()
    counts = dict(db.session.execute(
        select(GameIssue.status, func.count(GameIssue.id)).group_by(GameIssue.status)
    ).all())
    return render_template(
        'admin/admin_issues.html',
        groups=_group_issues(issues, game_uuids), pagination=pagination,
        selected_scope=scope, selected_category=category, search_term=search_term,
        status_counts=counts, status_labels=ISSUE_STATUSES,
        category_labels=ISSUE_CATEGORIES, open_statuses=OPEN_ISSUE_STATUSES,
        closed_statuses=CLOSED_ISSUE_STATUSES,
    )


@issues_bp.get('/admin/issues/<int:issue_id>')
@login_required
@admin_required
def admin_issue_detail(issue_id):
    issue = _issue_or_404(issue_id, admin=True)
    return render_template(
        'admin/admin_issue_detail.html', issue=issue,
        status_labels=ISSUE_STATUSES, category_labels=ISSUE_CATEGORIES,
    )


@issues_bp.post('/admin/issues/<int:issue_id>/update')
@login_required
@admin_required
def admin_update_issue(issue_id):
    issue = _issue_or_404(issue_id, admin=True)
    status = str(request.form.get('status') or '').strip()
    try:
        category, title, description = _validate_issue_payload(request.form)
        issue.category = category
        issue.title = title
        issue.description = description
        activity, previous_status = _transition_issue(issue, status, current_user)
        if activity is None:
            issue.handled_by_user_id = current_user.id
            db.session.commit()
        log_system_event(
            f'{current_user.name} updated issue {issue.id}'
            + (f' from {previous_status} to {status}' if activity else ''),
            event_type='game_issue', event_level='information',
        )
        flash('Issue updated.', 'success')
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(url_for('issues.admin_issue_detail', issue_id=issue.id))


@issues_bp.post('/admin/issues/<int:issue_id>/comments')
@login_required
@admin_required
def add_admin_comment(issue_id):
    issue = _issue_or_404(issue_id, admin=True)
    try:
        body = _validate_comment(request.form)
        comment = GameIssueComment(
            issue=issue,
            author_id=current_user.id,
            body=body,
            is_internal=request.form.get('is_internal') == 'on',
        )
        issue.handled_by_user_id = current_user.id
        db.session.add(comment)
        db.session.commit()
        notify_issue_comment(issue, comment)
        flash('Internal note added.' if comment.is_internal else 'Reply sent.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('issues.admin_issue_detail', issue_id=issue.id))


@issues_bp.post('/admin/issues/<int:issue_id>/delete')
@login_required
@admin_required
def delete_issue(issue_id):
    issue = _issue_or_404(issue_id, admin=True)
    issue_title = issue.title
    issue_game = issue.game.name
    notify_issue_deleted(issue, current_user.name)
    db.session.delete(issue)
    db.session.commit()
    log_system_event(
        f'{current_user.name} deleted issue {issue_id} ({issue_game}: {issue_title})',
        event_type='game_issue', event_level='warning',
    )
    flash('Issue permanently deleted.', 'success')
    return redirect(url_for('issues.admin_issues', status='all'))

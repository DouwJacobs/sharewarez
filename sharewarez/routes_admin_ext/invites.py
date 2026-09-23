from datetime import timedelta
import uuid

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from sharewarez import db
from sharewarez.forms import AdminInviteForm
from sharewarez.models import GlobalSettings, InviteToken, User
from sharewarez.utils.auth import admin_required
from sharewarez.utils.event_logging import log_system_event
from sharewarez.utils.invitations import (
    active_invitation_clause,
    generate_invitation_credential,
    invitation_status,
    utc_now,
)
from sharewarez.utils.smtp import send_invite_email

from . import admin2_bp


def _configured_site_url() -> str:
    try:
        settings = db.session.scalar(select(GlobalSettings))
    except Exception:
        db.session.rollback()
        settings = None
    return (settings.site_url if settings and settings.site_url else 'http://127.0.0.1').rstrip('/')


def _invitation_url(raw_token: str) -> str:
    return f"{_configured_site_url()}{url_for('login.accept_invite', token=raw_token)}"


def _load_invitation_page(*, created_invite_url=None, created_invitation=None):
    now = utc_now()
    try:
        users = db.session.scalars(select(User).order_by(func.lower(User.name))).all()
        active_counts = dict(db.session.execute(
            select(InviteToken.creator_user_id, func.count(InviteToken.id))
            .where(active_invitation_clause(now=now))
            .group_by(InviteToken.creator_user_id)
        ).all())
        invitations = db.session.scalars(
            select(InviteToken)
            .order_by(InviteToken.created_at.desc(), InviteToken.id.desc())
            .limit(100)
        ).all()
    except Exception:
        db.session.rollback()
        flash('Invitation data could not be loaded. Try again.', 'error')
        users = []
        active_counts = {}
        invitations = []
    return render_template(
        'admin/admin_manage_invites.html',
        form=AdminInviteForm(),
        users=users,
        user_active_invites=active_counts,
        invitations=invitations,
        invitation_statuses={item.id: invitation_status(item, now=now) for item in invitations},
        created_invite_url=created_invite_url,
        created_invitation=created_invitation,
        site_url=_configured_site_url(),
        title='Invitations',
    )


@admin2_bp.route('/admin/manage_invites', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_invites():
    """Show invitation lifecycle and retain member allowance administration."""
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        invites_number_str = request.form.get('invites_number')
        if not user_id:
            flash('User ID is required.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        try:
            uuid.UUID(user_id)
        except (ValueError, TypeError):
            flash('Invalid user ID format.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        try:
            invites_number = int(invites_number_str) if invites_number_str else 0
        except (ValueError, TypeError):
            flash('Invalid invite number provided. Please enter a valid number.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        if not 0 <= invites_number <= 1000:
            flash('Invitations to add must be between 0 and 1000.', 'error')
            return redirect(url_for('admin2.manage_invites'))

        try:
            user = db.session.scalar(select(User).where(User.user_id == user_id))
            if not user:
                flash('User not found.', 'error')
                return redirect(url_for('admin2.manage_invites'))
            user.invite_quota += invites_number
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('The invitation allowance could not be updated.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        log_system_event(
            f'Admin {current_user.name} added {invites_number} invitation allowances to user {user.user_id}',
            event_type='audit',
            event_level='information',
        )
        flash(f'{user.name} now has an invitation allowance of {user.invite_quota}.', 'success')
        return redirect(url_for('admin2.manage_invites'))

    return _load_invitation_page()


@admin2_bp.post('/admin/invitations')
@login_required
@admin_required
def create_invitation():
    form = AdminInviteForm()
    delivery = request.form.get('delivery', 'link')
    if delivery not in {'link', 'email'}:
        delivery = 'link'
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, 'error')
        return _load_invitation_page(), 400

    email = (form.email.data or '').strip().lower() or None
    if delivery == 'email' and not email:
        flash('Enter an email address to send the invitation.', 'error')
        return _load_invitation_page(), 400
    if email and db.session.scalar(select(User).where(func.lower(User.email) == email)):
        flash('That email address already belongs to an account.', 'error')
        return _load_invitation_page(), 400

    raw_token, token_digest = generate_invitation_credential()
    invitation = InviteToken(
        token_digest=token_digest,
        creator_user_id=current_user.user_id,
        recipient_email=email,
        expires_at=utc_now() + timedelta(days=form.expires_days.data),
    )
    db.session.add(invitation)
    db.session.commit()
    invite_url = _invitation_url(raw_token)
    log_system_event(
        f'Admin {current_user.name} created invitation {invitation.id}',
        event_type='audit',
        event_level='information',
    )

    if delivery == 'email':
        if send_invite_email(email, invite_url, current_user.name):
            flash('Invitation sent. The recipient will choose their own username and password.', 'success')
            return redirect(url_for('admin2.manage_invites'))
        flash('Email delivery failed. Copy the one-time invitation link below instead.', 'warning')
    else:
        flash('Invitation created. Copy the link now; it will not be shown again.', 'success')
    return _load_invitation_page(
        created_invite_url=invite_url,
        created_invitation=invitation,
    ), 201


@admin2_bp.post('/admin/invitations/<int:invitation_id>/revoke')
@login_required
@admin_required
def revoke_invitation(invitation_id):
    invitation = db.session.get(InviteToken, invitation_id)
    if not invitation or invitation_status(invitation) != 'pending':
        flash('Only a pending invitation can be revoked.', 'warning')
        return redirect(url_for('admin2.manage_invites'))
    invitation.revoked_at = utc_now()
    invitation.revoked_by_user_id = current_user.user_id
    db.session.commit()
    log_system_event(
        f'Admin {current_user.name} revoked invitation {invitation.id}',
        event_type='audit',
        event_level='warning',
    )
    flash('Invitation revoked.', 'success')
    return redirect(url_for('admin2.manage_invites'))


@admin2_bp.post('/admin/invitations/<int:invitation_id>/replace')
@login_required
@admin_required
def replace_invitation(invitation_id):
    invitation = db.session.get(InviteToken, invitation_id)
    if not invitation or invitation.used:
        flash('Accepted invitations cannot be replaced.', 'warning')
        return redirect(url_for('admin2.manage_invites'))

    invitation.revoked_at = invitation.revoked_at or utc_now()
    invitation.revoked_by_user_id = current_user.user_id
    raw_token, token_digest = generate_invitation_credential()
    replacement = InviteToken(
        token_digest=token_digest,
        creator_user_id=current_user.user_id,
        recipient_email=invitation.recipient_email,
        expires_at=utc_now() + timedelta(days=7),
    )
    db.session.add(replacement)
    db.session.commit()
    invite_url = _invitation_url(raw_token)
    log_system_event(
        f'Admin {current_user.name} replaced invitation {invitation.id} with invitation {replacement.id}',
        event_type='audit',
        event_level='information',
    )

    delivery = request.form.get('delivery', 'link')
    if delivery == 'email' and replacement.recipient_email:
        if send_invite_email(replacement.recipient_email, invite_url, current_user.name):
            flash('Replacement invitation sent.', 'success')
            return redirect(url_for('admin2.manage_invites'))
        flash('Email delivery failed. Copy the replacement link below.', 'warning')
    else:
        flash('Replacement created. Copy the link now; it will not be shown again.', 'success')
    return _load_invitation_page(
        created_invite_url=invite_url,
        created_invitation=replacement,
    ), 201

import uuid
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app, abort
from flask_login import current_user, login_required
from sharewarez import db
from sharewarez.models import User, InviteToken, GlobalSettings, Whitelist
from sharewarez.forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, InviteForm, UserPasswordForm
from sharewarez.utils.auth import _authenticate_and_redirect, get_safe_next_url
from sharewarez.utils.smtp import send_email, send_password_reset_email, send_invite_email
from sharewarez.utils.processors import get_global_settings
from sharewarez.utils.event_logging import log_system_event
from sharewarez import cache
from sharewarez.security import limiter
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from uuid import uuid4
from sqlalchemy.exc import IntegrityError



login_bp = Blueprint('login', __name__)

def get_serializer():
    """Get URLSafeTimedSerializer with current app's secret key."""
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

def is_smtp_configured():
    """Check if SMTP settings are properly configured."""
    settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
    if not settings:
        return False
    return bool(settings.smtp_server and 
                settings.smtp_port and 
                settings.smtp_username and 
                settings.smtp_password)

@login_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Context processor to inject global settings into templates"""
    return get_global_settings()

@login_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def login():
    next_page = get_safe_next_url()
    if current_user.is_authenticated:
        return redirect(next_page or url_for('discover.discover'))


    form = LoginForm()
    if request.method == 'POST' and form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = db.session.execute(select(User).filter_by(name=username)).scalar_one_or_none()

        if user:
            if not user.is_email_verified:
                flash('Your account is not activated, check your email.', 'warning')
                log_system_event(f"User {username} attempted to log in with an unverified account.", event_type='login', event_level='warning')
                return redirect(url_for('login.login', next=next_page) if next_page else url_for('login.login'))

            if not user.state:
                flash('Your account has been banned.', 'error')
                log_system_event(f"User {username} attempted to log in with a banned account.", event_type='login', event_level='warning')
                return redirect(url_for('login.login', next=next_page) if next_page else url_for('login.login'))

            log_system_event(f"User {username} logged in successfully.", event_type='login', event_level='information')
            return _authenticate_and_redirect(username, password)
        else:
            flash('Invalid username or password. USERNAMES ARE CASE SENSITIVE!', 'error')
            log_system_event(f"User {username} attempted to log in with invalid credentials.", event_type='login', event_level='warning')
            return redirect(url_for('login.login', next=next_page) if next_page else url_for('login.login'))

    return render_template('login/login.html', form=form, next_page=next_page)


@login_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('login.login'))

    # Attempt to get the invite token from the query parameters
    invite_token_from_url = request.args.get('token')
    invite = None
    if invite_token_from_url:
        invite = db.session.execute(select(InviteToken).filter_by(token=invite_token_from_url, used=False).with_for_update()).scalar_one_or_none()
        if invite:
            # Handle timezone comparison safely
            current_time = datetime.now(timezone.utc)
            if invite.expires_at.tzinfo:
                # Timezone-aware comparison
                is_valid = invite.expires_at >= current_time
            else:
                # Timezone-naive comparison
                naive_current = current_time.replace(tzinfo=None)
                is_valid = invite.expires_at >= naive_current
            
            if is_valid:
                # The invite is valid; skip the whitelist check later
                pass
            else:
                invite = None  # Invalidate
                flash('The invite is invalid or has expired.', 'warning')
                return redirect(url_for('login.register'))
        else:
            invite = None  # Invalidate
            flash('The invite is invalid or has expired.', 'warning')
            return redirect(url_for('login.register'))
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            registration_unavailable_message = (
                'Registration could not be completed. Check your details or invite, '
                'or contact an administrator.'
            )
            email_address = form.email.data.strip().lower()
            existing_user_email = db.session.execute(select(User).filter(func.lower(User.email) == email_address)).scalar_one_or_none()
            if existing_user_email:
                flash(registration_unavailable_message, 'warning')
                return redirect(url_for('login.register'))
                    # Proceed with the whitelist check only if no valid invite token is provided
            if not invite:
                whitelist = db.session.execute(select(Whitelist).filter(func.lower(Whitelist.email) == email_address)).scalar_one_or_none()
                if not whitelist:
                    flash(registration_unavailable_message, 'warning')
                    return redirect(url_for('login.register'))

            existing_user = db.session.execute(select(User).filter_by(name=form.username.data)).scalar_one_or_none()
            if existing_user is not None:
                flash(registration_unavailable_message, 'warning')
                return redirect(url_for('login.register'))

            user_uuid = str(uuid4())
            existing_uuid = db.session.execute(select(User).filter_by(user_id=user_uuid)).scalar_one_or_none()
            if existing_uuid is not None:
                flash('An error occurred while registering. Please try again.', 'error')
                return redirect(url_for('login.register'))

            user = User(
                user_id=user_uuid,
                name=form.username.data,
                email=email_address,
                role='user',
                is_email_verified=False,
                email_verification_token=get_serializer().dumps(email_address, salt='email-confirm'),
                token_creation_time=datetime.now(timezone.utc),
                created=datetime.now(timezone.utc)
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            if invite:
                invite.used = True
                invite.used_by = user.user_id
                invite.used_at = datetime.now(timezone.utc)
            db.session.commit()
            log_system_event(f"New user registered: {user.name}", event_type='audit', event_level='information')

            # Verification email
            verification_token = user.email_verification_token
            confirm_url = url_for('login.confirm_email', token=verification_token, _external=True)
            from sharewarez.utils.email_templates import render_system_email
            subject, html = render_system_email('account_confirmation', {
                'user_name': user.name,
                'confirm_url': confirm_url,
                'expires_in': '15 minutes',
            })
            delivered = send_email(user.email, subject, html, show_feedback=False)


            if delivered:
                flash('Account created. Check your email for the confirmation link.', 'success')
            else:
                flash('Account created, but the confirmation email could not be sent. Request a new activation link or contact an administrator.', 'warning')
            return redirect(url_for('site.index'))
        except IntegrityError:
            db.session.rollback()
            flash('Error while registering. Please try again.', 'error')

    return render_template('login/registration.html', title='Register', form=form)


@login_bp.route('/confirm/<token>')
@limiter.limit('20 per minute')
def confirm_email(token):
    try:
        email = get_serializer().loads(token, salt='email-confirm', max_age=900)  # 15 minutes
    except SignatureExpired:
        return render_template('login/confirmation_expired.html'), 400
    except BadSignature:
        return render_template('login/confirmation_invalid.html'), 400

    user = db.session.execute(select(User).filter(func.lower(User.email) == str(email).strip().lower())).scalar_one_or_none() or abort(404)
    if user.is_email_verified:
        return render_template('login/registration_already_confirmed.html')
    else:
        user.is_email_verified = True
        db.session.add(user)
        db.session.commit()
        return render_template('login/confirmation_success.html')


@login_bp.route('/reset_password_request', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('login.login'))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = db.session.execute(select(User).filter_by(email=form.email.data.lower())).scalar_one_or_none()
        if user:
            # Generate a unique token
            token = get_serializer().dumps(user.email, salt='password-reset-salt')
            user.password_reset_token = token
            user.token_creation_time = datetime.now(timezone.utc)
            
            log_system_event(f"Password reset requested for user: {user.email}", event_type='password_reset', event_level='information')
            
            db.session.commit()

            # Send reset email
            try:
                if not send_password_reset_email(user.email, token, user.name):
                    log_system_event('Password reset email delivery failed', event_type='password_reset', event_level='error')
            except Exception:
                # Keep the public response indistinguishable from an unknown
                # address while recording an actionable server-side event.
                log_system_event(
                    'Password reset email delivery failed',
                    event_type='password_reset',
                    event_level='error'
                )

        # Use the same response and destination whether or not an account was
        # found so this public endpoint cannot be used to enumerate users.
        flash(
            'If an account exists for that email, password reset instructions have been sent.',
            'success'
        )
        return redirect(url_for('login.login'))

    return render_template('login/reset_password_request.html', title='Reset Password', form=form)


def _as_utc(value):
    """Legacy timestamp-without-time-zone columns contain UTC values."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@login_bp.route('/request_new_activation', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def request_new_activation():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(select(User).where(func.lower(User.email) == email))
        if user and not user.is_email_verified and user.state:
            user.email_verification_token = get_serializer().dumps(email, salt='email-confirm')
            db.session.commit()
            from sharewarez.utils.email_templates import render_system_email
            subject, html = render_system_email('account_confirmation', {
                'user_name': user.name,
                'confirm_url': url_for('login.confirm_email', token=user.email_verification_token, _external=True),
                'expires_in': '15 minutes',
            })
            try:
                delivered = send_email(user.email, subject, html, show_feedback=False)
            except Exception:
                delivered = False
            if not delivered:
                log_system_event('Activation email delivery failed', event_type='email', event_level='error')
        flash('If an account needs activation, a confirmation link has been requested. Contact an administrator if it does not arrive.', 'success')
        return redirect(url_for('login.login'))
    return render_template('login/request_new_activation.html', title='Request activation link', form=form)

@login_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('login.login'))

    user = db.session.execute(select(User).filter_by(password_reset_token=token)).scalar_one_or_none()
    if not user or not user.token_creation_time or _as_utc(user.token_creation_time) + timedelta(minutes=15) < datetime.now(timezone.utc):
        flash('The password reset link is invalid or has expired.', 'warning')
        return redirect(url_for('login.login'))

    form = UserPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.password_reset_token = None
        user.token_creation_time = None
        db.session.commit()
        flash('Your password has been reset.', 'success')
        return redirect(url_for('login.login'))

    return render_template('login/reset_password.html', form=form, token=token)


@login_bp.route('/user/invites', methods=['GET', 'POST'])
@login_required
def invites():
    settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
    site_url = settings.site_url if settings else 'http://127.0.0.1'
    smtp_enabled = is_smtp_configured()
    if site_url == 'http://127.0.0.1'and current_user.role == 'admin':
        flash('Please configure the site URL in the admin settings.', 'danger')
    form = InviteForm()
    if form.validate_on_submit():
        email = request.form.get('email')
        # Ensure the user has invites left to send
        current_invites = db.session.scalar(select(func.count(InviteToken.id)).filter_by(creator_user_id=current_user.user_id, used=False))
        if current_user.invite_quota > current_invites:
            token = str(uuid.uuid4())
            invite_token = InviteToken(
                token=token, 
                creator_user_id=current_user.user_id,
                recipient_email=email
            )
            db.session.add(invite_token)
            db.session.commit()

            settings = db.session.execute(select(GlobalSettings)).scalar_one_or_none()
            site_url = settings.site_url if settings else 'http://127.0.0.1'
            
            # Build the invite URL using the configured site URL
            invite_url = f"{site_url}/register?token={token}"

            if send_invite_email(email, invite_url, current_user.name):
                flash('Invite sent successfully. The invite expires after 48 hours.', 'success')
            else:
                flash('Invite created, but email delivery failed. You can copy its link below.', 'warning')
        else:
            flash('You have reached your invite limit.', 'danger')
        return redirect(url_for('login.invites'))

    invites = db.session.execute(select(InviteToken).filter_by(creator_user_id=current_user.user_id, used=False)).scalars().all()
    current_invites_count = len(invites)
    remaining_invites = max(0, current_user.invite_quota - current_invites_count)

    return render_template('/login/user_invites.html', 
                         form=form, 
                         invites=invites, 
                         invite_quota=current_user.invite_quota, 
                         site_url=site_url, 
                         smtp_enabled=smtp_enabled,
                         current_invites_count=current_invites_count, 
                         remaining_invites=remaining_invites, 
                         current_datetime=datetime.now(timezone.utc))

@login_bp.route('/delete_invite/<token>', methods=['POST'])
@login_required
def delete_invite(token):
    try:
        invite = db.session.execute(select(InviteToken).filter_by(token=token, creator_user_id=current_user.user_id)).scalar_one_or_none()
        if invite:
            db.session.delete(invite)
            db.session.commit()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Invite not found or you do not have permission to delete it.'})
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred while deleting the invite.'}), 500

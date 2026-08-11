from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sharewarez import db
from sharewarez.utils.auth import admin_required
from sharewarez.utils.email_templates import (
    TEMPLATE_DEFINITIONS,
    get_template_definition,
    get_template_source,
    render_preview,
    reset_template,
    save_template,
)
from sharewarez.utils.event_logging import log_system_event
from . import admin2_bp


def _selected_key(value):
    return value if value in TEMPLATE_DEFINITIONS else next(iter(TEMPLATE_DEFINITIONS))


@admin2_bp.route('/admin/email-templates', methods=['GET', 'POST'])
@login_required
@admin_required
def email_templates():
    selected_key = _selected_key(request.form.get('template_key') or request.args.get('template'))
    if request.method == 'POST':
        try:
            save_template(
                selected_key,
                request.form.get('subject', ''),
                request.form.get('html', ''),
                current_user.id,
            )
            log_system_event(
                f'System email template {selected_key} updated by {current_user.name}',
                event_type='audit',
                event_level='information',
            )
            flash('Email template saved.', 'success')
            return redirect(url_for('admin2.email_templates', template=selected_key))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Unable to save system email template')
            flash('The email template could not be saved.', 'error')

    templates = [get_template_source(key) for key in TEMPLATE_DEFINITIONS]
    selected = get_template_source(selected_key)
    subject = request.form.get('subject', str(selected['subject']))
    html = request.form.get('html', str(selected['html']))
    try:
        preview_subject, preview_html = render_preview(selected_key, subject, html)
    except ValueError:
        preview_subject, preview_html = '', ''
    return render_template(
        'admin/admin_email_templates.html',
        templates=templates,
        selected=selected,
        subject=subject,
        html=html,
        preview_subject=preview_subject,
        preview_html=preview_html,
    )


@admin2_bp.post('/admin/email-templates/<template_key>/preview')
@login_required
@admin_required
def preview_email_template(template_key):
    try:
        subject, html = render_preview(
            template_key,
            request.form.get('subject', ''),
            request.form.get('html', ''),
        )
        return jsonify({'success': True, 'subject': subject, 'html': html})
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@admin2_bp.post('/admin/email-templates/<template_key>/reset')
@login_required
@admin_required
def reset_email_template(template_key):
    try:
        definition = get_template_definition(template_key)
        reset_template(template_key)
        log_system_event(
            f'System email template {template_key} reset by {current_user.name}',
            event_type='audit',
            event_level='information',
        )
        flash(f'{definition.name} reset to its default.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Unable to reset system email template')
        flash('The email template could not be reset.', 'error')
    return redirect(url_for('admin2.email_templates', template=_selected_key(template_key)))

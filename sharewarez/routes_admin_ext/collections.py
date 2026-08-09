import json

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from sharewarez import db
from sharewarez.forms import CollectionForm, CsrfProtectForm
from sharewarez.models import Collection, CollectionGame, Game, Image
from sharewarez.utils.auth import admin_required
from sharewarez.utils.collections import (
    parse_smart_rules, replace_collection_games,
    smart_collection_statement, unique_collection_slug,
)
from sharewarez.utils.event_logging import log_system_event

from . import admin2_bp


def _ordered_uuids(raw_value):
    return [value.strip() for value in (raw_value or '').split(',') if value.strip()]


def _collection_name_exists(name, collection_id=None):
    query = select(Collection.id).where(func.lower(Collection.name) == name.strip().lower())
    if collection_id is not None:
        query = query.where(Collection.id != collection_id)
    return db.session.execute(query).scalar_one_or_none() is not None


def _set_parent_choices(form, collection_id=None):
    roots = db.session.execute(
        select(Collection).where(Collection.parent_id.is_(None), Collection.id != collection_id).order_by(Collection.name)
    ).scalars().all()
    form.parent_id.choices = [(0, 'No group')] + [(item.id, item.name) for item in roots]


@admin2_bp.route('/admin/collections')
@login_required
@admin_required
def collections():
    items = db.session.execute(
        select(Collection)
        .options(selectinload(Collection.game_links))
        .order_by(Collection.is_featured.desc(), Collection.display_order, Collection.name)
    ).scalars().all()
    return render_template(
        'admin/admin_manage_collections.html',
        collections=items,
        csrf_form=CsrfProtectForm(),
        title='Collections',
    )


@admin2_bp.route('/admin/collections/new', methods=['GET', 'POST'])
@login_required
@admin_required
def add_collection():
    form = CollectionForm()
    _set_parent_choices(form)
    if form.validate_on_submit():
        smart_rules = None
        if form.is_smart.data:
            try:
                smart_rules = parse_smart_rules(form.smart_rules.data)
            except ValueError as exc:
                form.smart_rules.errors.append(str(exc))
        if _collection_name_exists(form.name.data):
            form.name.errors.append('A collection with this name already exists.')
        elif not form.errors:
            item = Collection(
                name=form.name.data.strip(),
                slug=unique_collection_slug(form.name.data),
                description=(form.description.data or '').strip() or None,
                artwork_url=(form.artwork_url.data or '').strip() or None,
                parent_id=form.parent_id.data or None,
                visibility=form.visibility.data,
                owner_id=current_user.id,
                show_on_discover=form.show_on_discover.data,
                display_order=form.display_order.data or 0,
                is_smart=form.is_smart.data,
                smart_rules=smart_rules,
                smart_sort=form.smart_sort.data,
                smart_sort_order=form.smart_sort_order.data,
                smart_limit=form.smart_limit.data or 24,
            )
            db.session.add(item)
            if not item.is_smart:
                replace_collection_games(item, _ordered_uuids(form.game_order.data))
            db.session.commit()
            log_system_event(f'Collection created: {item.name}', event_type='collection')
            flash('Collection created.', 'success')
            return redirect(url_for('admin2.collections'))
    return render_template('admin/admin_collection_editor.html', form=form, collection=None, title='New collection')


@admin2_bp.route('/admin/collections/<int:collection_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_collection(collection_id):
    item = db.session.execute(
        select(Collection)
        .options(selectinload(Collection.game_links).selectinload(CollectionGame.game))
        .where(Collection.id == collection_id)
    ).scalar_one_or_none() or abort(404)
    form = CollectionForm(obj=item)
    _set_parent_choices(form, item.id)
    if request.method == 'GET':
        form.parent_id.data = item.parent_id or 0
        form.game_order.data = ','.join(link.game_uuid for link in item.game_links)
        form.smart_rules.data = json.dumps(item.smart_rules, indent=2) if item.smart_rules else ''

    if form.validate_on_submit():
        smart_rules = None
        wants_smart = bool(form.is_smart.data and not item.is_featured)
        if wants_smart:
            try:
                smart_rules = parse_smart_rules(form.smart_rules.data)
            except ValueError as exc:
                form.smart_rules.errors.append(str(exc))
        if _collection_name_exists(form.name.data, item.id):
            form.name.errors.append('A collection with this name already exists.')
        elif not form.errors:
            if not item.is_featured:
                item.name = form.name.data.strip()
                item.slug = unique_collection_slug(item.name, item.id)
                item.show_on_discover = form.show_on_discover.data
                item.display_order = form.display_order.data or 0
                item.parent_id = form.parent_id.data or None
                item.artwork_url = (form.artwork_url.data or '').strip() or None
                item.visibility = form.visibility.data
                if item.owner_id is None:
                    item.owner_id = current_user.id
                item.is_smart = wants_smart
                item.smart_rules = smart_rules
                item.smart_sort = form.smart_sort.data
                item.smart_sort_order = form.smart_sort_order.data
                item.smart_limit = form.smart_limit.data or 24
            item.description = (form.description.data or '').strip() or None
            if item.is_smart:
                item.game_links.clear()
            else:
                replace_collection_games(item, _ordered_uuids(form.game_order.data))
            db.session.commit()
            log_system_event(f'Collection updated: {item.name}', event_type='collection')
            flash('Collection updated.', 'success')
            return redirect(url_for('admin2.collections'))
    return render_template('admin/admin_collection_editor.html', form=form, collection=item, title='Edit collection')


@admin2_bp.route('/admin/collections/<int:collection_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_collection(collection_id):
    item = db.session.get(Collection, collection_id) or abort(404)
    if item.is_featured:
        flash('The Featured Games collection is required and cannot be deleted.', 'error')
        return redirect(url_for('admin2.collections'))
    name = item.name
    db.session.delete(item)
    db.session.commit()
    log_system_event(f'Collection deleted: {name}', event_type='collection')
    flash('Collection deleted.', 'success')
    return redirect(url_for('admin2.collections'))


@admin2_bp.route('/admin/api/collections/games')
@login_required
@admin_required
def search_collection_games():
    query_text = request.args.get('q', '').strip()
    statement = (
        select(Game.uuid, Game.name, Image.url)
        .outerjoin(Image, (Image.game_uuid == Game.uuid) & (Image.image_type == 'cover'))
        .order_by(Game.name)
        .limit(30)
    )
    if query_text:
        statement = statement.where(Game.name.ilike(f'%{query_text}%'))
    rows = db.session.execute(statement).all()
    seen = set()
    results = []
    for game_uuid, name, cover_url in rows:
        if game_uuid in seen:
            continue
        seen.add(game_uuid)
        results.append({'uuid': game_uuid, 'name': name, 'cover_url': cover_url})
    return jsonify({'games': results})


@admin2_bp.route('/admin/api/collections/smart-preview', methods=['POST'])
@login_required
@admin_required
def preview_smart_collection():
    data = request.get_json(silent=True) or {}
    try:
        rules = parse_smart_rules(data.get('rules'))
        statement = smart_collection_statement(
            rules, data.get('sort', 'name'), data.get('sort_order', 'asc'),
            min(int(data.get('limit', 24)), 50),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    games = db.session.execute(statement).scalars().unique().all()
    return jsonify({'count': len(games), 'games': [
        {'uuid': game.uuid, 'name': game.name, 'rating': game.rating,
         'library_name': game.library.name if game.library else None}
        for game in games
    ]})

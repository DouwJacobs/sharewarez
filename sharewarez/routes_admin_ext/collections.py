from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from sharewarez import db
from sharewarez.forms import CollectionForm, CsrfProtectForm
from sharewarez.models import Collection, CollectionGame, Game, Image
from sharewarez.utils.auth import admin_required
from sharewarez.utils.collections import replace_collection_games, unique_collection_slug
from sharewarez.utils.event_logging import log_system_event

from . import admin2_bp


def _ordered_uuids(raw_value):
    return [value.strip() for value in (raw_value or '').split(',') if value.strip()]


def _collection_name_exists(name, collection_id=None):
    query = select(Collection.id).where(func.lower(Collection.name) == name.strip().lower())
    if collection_id is not None:
        query = query.where(Collection.id != collection_id)
    return db.session.execute(query).scalar_one_or_none() is not None


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
    if form.validate_on_submit():
        if _collection_name_exists(form.name.data):
            form.name.errors.append('A collection with this name already exists.')
        else:
            item = Collection(
                name=form.name.data.strip(),
                slug=unique_collection_slug(form.name.data),
                description=(form.description.data or '').strip() or None,
                show_on_discover=form.show_on_discover.data,
                display_order=form.display_order.data or 0,
            )
            db.session.add(item)
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
    if request.method == 'GET':
        form.game_order.data = ','.join(link.game_uuid for link in item.game_links)

    if form.validate_on_submit():
        if _collection_name_exists(form.name.data, item.id):
            form.name.errors.append('A collection with this name already exists.')
        else:
            if not item.is_featured:
                item.name = form.name.data.strip()
                item.slug = unique_collection_slug(item.name, item.id)
                item.show_on_discover = form.show_on_discover.data
                item.display_order = form.display_order.data or 0
            item.description = (form.description.data or '').strip() or None
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

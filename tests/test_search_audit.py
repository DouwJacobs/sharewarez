"""Search bootstrap, bounded results and realistic PostgreSQL query plans."""
from time import perf_counter
from uuid import uuid4
import json
from sqlalchemy import text
from sharewarez import db
from sharewarez.models import Game, Library, User
from sharewarez.platform import LibraryPlatform
from sharewarez.routes_apis.search import _ranked_search
from sharewarez.utils.migrations import bootstrap_schema_extras, stamp_database, upgrade_database


def test_fresh_bootstrap_and_stamped_repair(app, db_session):
    db_session.commit()
    with db.engine.begin() as connection:
        connection.execute(text('DROP EXTENSION IF EXISTS pg_trgm CASCADE'))
    bootstrap_schema_extras(db.engine)
    with db.engine.connect() as connection:
        assert connection.scalar(text("SELECT similarity('game', 'game')")) == 1
        assert connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname LIKE '%_name_distance'")) == 5
    # Reproduce metadata-created schemas already stamped at the former head.
    db.session.remove()
    db.engine.dispose()
    with db.engine.begin() as connection:
        connection.execute(text('DROP EXTENSION pg_trgm CASCADE'))
    stamp_database(app.config['SQLALCHEMY_DATABASE_URI'], '20260904_24')
    upgrade_database(app.config['SQLALCHEMY_DATABASE_URI'])
    upgrade_database(app.config['SQLALCHEMY_DATABASE_URI'])
    with db.engine.connect() as connection:
        assert connection.scalar(text("SELECT similarity('game', 'game')")) == 1
        assert connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname LIKE '%_name_distance'")) == 5


def test_large_catalogue_query_plan_and_limits(app, client, db_session):
    library = Library(name='Search benchmark', platform=LibraryPlatform.PCWIN)
    user = User(name=uuid4().hex, email=uuid4().hex+'@example.com', role='user', state=True, password_hash='unused')
    db_session.add_all([library, user]); db_session.flush()
    db_session.execute(Game.__table__.insert(), [
        {'name': f'Collection {uuid4().hex} game {i}', 'library_uuid': library.uuid}
        for i in range(10000)
    ] + [{'name':'Unique Zephyr Adventure', 'library_uuid': library.uuid},
         {'name':'Literal 100% Hero', 'library_uuid': library.uuid}])
    db_session.commit()
    with db.engine.begin() as connection:
        connection.execute(text('ANALYZE games'))
    measurements = {}
    for query in ['Zephyr', 'game']:
        statement = _ranked_search(Game, Game.name, (Game.name, Game.summary), query, 8)
        compiled = statement.compile(db.engine)
        plan = db_session.connection().exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + str(compiled), compiled.params).scalar()[0]
        started = perf_counter()
        rows = db_session.execute(statement).all()
        measurements[query] = {'sql_ms': plan['Execution Time'], 'orm_ms': (perf_counter()-started)*1000, 'plan':plan['Plan']}
        assert len(rows) <= 8
        plan_text = json.dumps(plan)
        assert 'ix_games_name_distance' in plan_text
        if query == 'Zephyr':
            assert any(game.name == 'Unique Zephyr Adventure' for game, _ in rows)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    assert len(client.get('/api/search?query=game').get_json()) == 20
    assert [row['name'] for row in client.get('/api/search?query=%25').get_json()] == ['Literal 100% Hero']
    assert client.get('/api/global-search?q=' + 'a'*101).status_code == 400
    from pathlib import Path
    Path('/tmp/sharewarez-search-benchmark.json').write_text(json.dumps(measurements, indent=2))
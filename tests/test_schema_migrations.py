import sqlite3

import pytest
from sqlalchemy import create_engine,inspect,text

from app.db.session import Base
from app.models import models  # noqa: F401
from app.db.schema import migrate_database,schema_status,SchemaStateError,migration_config
from alembic import command


def test_fresh_database_uses_revision_and_is_repeatable(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'fresh.sqlite').as_posix()}")
    result=migrate_database(engine)
    assert result=={'status':'upgraded','revision':'0002','backup_created':False}
    assert schema_status(engine)['is_current']
    assert set(Base.metadata.tables).issubset(inspect(engine).get_table_names())
    assert migrate_database(engine)['status']=='current'
    engine.dispose()


def test_matching_legacy_database_requires_explicit_adoption_and_verified_backup(tmp_path):
    path=tmp_path/'existing.sqlite';engine=create_engine(f'sqlite:///{path.as_posix()}')
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), '0001')
        connection.exec_driver_sql('DROP TABLE alembic_version')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO customers (customer_id,previous_failures) VALUES ('keep',7)"))
    with pytest.raises(SchemaStateError,match='adopt-legacy'):migrate_database(engine)
    assert 'alembic_version' not in inspect(engine).get_table_names()
    result=migrate_database(engine,adopt_legacy=True,backup_directory=tmp_path/'backups')
    assert result['status']=='adopted' and result['backup_created']
    assert schema_status(engine)['is_current']
    with engine.connect() as connection:assert connection.execute(text('SELECT previous_failures FROM customers')).scalar()==7
    backup=next((tmp_path/'backups').glob('*.sqlite'))
    with sqlite3.connect(backup) as copied:
        assert copied.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert copied.execute('SELECT previous_failures FROM customers').fetchone()[0]==7
    engine.dispose()


def test_unknown_legacy_shape_is_not_stamped_or_modified(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'foreign.sqlite').as_posix()}")
    with engine.begin() as connection:connection.exec_driver_sql('CREATE TABLE unrelated (value TEXT)')
    with pytest.raises(SchemaStateError,match='differs'):migrate_database(engine,adopt_legacy=True)
    assert inspect(engine).get_table_names()==['unrelated']
    engine.dispose()


def test_unknown_revision_is_not_upgraded(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'unknown.sqlite').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)')
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('future_unknown')")
    with pytest.raises(SchemaStateError,match='Unknown'):migrate_database(engine)
    engine.dispose()


def test_existing_migration_lock_is_never_forcibly_removed(tmp_path):
    path=tmp_path/'locked.sqlite';lock=tmp_path/'locked.sqlite.migration.lock'
    lock.write_text('other-owner')
    engine=create_engine(f'sqlite:///{path.as_posix()}')
    with pytest.raises(SchemaStateError,match='lock already exists'):migrate_database(engine)
    assert lock.read_text()=='other-owner'
    engine.dispose()

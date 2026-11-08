"""Versioned schema checks with a strict, frozen legacy baseline."""

from contextlib import contextmanager
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

ROOT=Path(__file__).resolve().parents[2]


class SchemaStateError(RuntimeError):
    pass


def migration_config(connection=None):
    config=Config(str(ROOT/'alembic.ini'))
    if connection is not None:config.attributes['connection']=connection
    return config


def schema_signature(connection):
    inspector=inspect(connection);result={}
    for table in sorted(set(inspector.get_table_names())-{'alembic_version'}):
        result[table]={
            'columns':sorted([{'name':c['name'],'type':str(c['type']).upper(),
                               'nullable':bool(c['nullable']),'default':c.get('default')}
                              for c in inspector.get_columns(table)],key=lambda c:c['name']),
            'primary_key':inspector.get_pk_constraint(table)['constrained_columns'],
            'unique':sorted([list(c['column_names']) for c in inspector.get_unique_constraints(table)]),
            'indexes':sorted([{'columns':list(i['column_names']),'unique':bool(i['unique'])}
                              for i in inspector.get_indexes(table)],key=lambda i:(i['columns'],i['unique'])),
            'foreign_keys':sorted([{'columns':list(f['constrained_columns']),'table':f['referred_table'],
                                   'target':list(f['referred_columns']),'options':f.get('options') or {}}
                                  for f in inspector.get_foreign_keys(table)],key=lambda f:(f['columns'],f['table'])),
        }
    return result


def schema_status(engine):
    heads=ScriptDirectory.from_config(migration_config()).get_heads()
    with engine.connect() as connection:
        current=list(MigrationContext.configure(connection).get_current_heads())
    return {'current':current,'expected':heads,'is_current':sorted(current)==sorted(heads)}


@contextmanager
def migration_lock(engine):
    database=engine.url.database
    if engine.dialect.name!='sqlite' or database in (None,':memory:'):
        yield
        return
    path=Path(database).resolve().with_suffix(Path(database).suffix+'.migration.lock')
    token=uuid.uuid4().hex
    try:
        descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise SchemaStateError('Migration lock already exists. Verify no migrator is running before reviewing the lock.') from None
    try:
        with os.fdopen(descriptor,'w') as file:file.write(token)
        yield
    finally:
        if path.exists() and path.read_text()==token:path.unlink()


def backup_sqlite(engine,directory):
    source=Path(engine.url.database).resolve()
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    name='recoverai-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex+'.sqlite'
    target=directory/name
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as current:
        with sqlite3.connect(target) as backup:
            current.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise SchemaStateError('Backup integrity verification failed; migration stopped')
    return target


def migrate_database(engine,*,adopt_legacy=False,backup_directory=None):
    """Run during maintenance with app/workers stopped. Never infer legacy compatibility."""
    scripts=ScriptDirectory.from_config(migration_config());heads=scripts.get_heads()
    if len(heads)!=1:raise SchemaStateError('A single reviewed migration head is required')
    with migration_lock(engine):
        with engine.connect() as connection:
            current=list(MigrationContext.configure(connection).get_current_heads())
            tables=set(inspect(connection).get_table_names())-{'alembic_version'}
            signature=schema_signature(connection) if not current and tables else None
            if engine.dialect.name=='sqlite' and tables and connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
                raise SchemaStateError('Existing data has broken references; migration stopped for review')
        if len(current)>1:raise SchemaStateError('Multiple database revisions need manual review')
        if current:
            try:scripts.get_revision(current[0])
            except Exception:raise SchemaStateError('Unknown database revision; migration stopped') from None
        legacy=not current and bool(tables)
        if legacy:
            if not adopt_legacy:raise SchemaStateError('Existing unversioned database needs explicit --adopt-legacy after stopping services')
            if engine.dialect.name!='sqlite':raise SchemaStateError('Automatic legacy adoption supports SQLite only')
            expected=json.loads((ROOT/'migrations/baseline_schema.json').read_text(encoding='utf-8'))
            if signature!=expected:
                raise SchemaStateError('Existing schema differs from the frozen baseline; no version stamp or schema changes applied')
        backup=None
        needs_change=not current or current!=heads
        if needs_change and tables and engine.dialect.name=='sqlite' and engine.url.database!=':memory:':
            backup=backup_sqlite(engine,backup_directory or ROOT/'var/backups')
        with engine.begin() as connection:
            config=migration_config(connection)
            if legacy:command.stamp(config,'0001')
            if needs_change:command.upgrade(config,'head')
            command.check(config)
        return {'status':'adopted' if legacy else 'upgraded' if needs_change else 'current',
                'revision':heads[0],'backup_created':backup is not None}

"""Verify a SQLite backup by restoring/migrating a unique disposable copy.

Never overwrite a configured database or write to the backup source.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from sqlalchemy import create_engine,inspect
from app.db.schema import migrate_database,schema_status

ROOT=Path(__file__).resolve().parents[1]


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def quote(identifier):
    return '"'+identifier.replace('"','""')+'"'


def snapshot(connection,columns=None):
    result={}
    inspector=inspect(connection)
    tables=columns or {table:[c['name'] for c in inspector.get_columns(table)]
                      for table in inspector.get_table_names() if table!='alembic_version'}
    for table,names in tables.items():
        fields=','.join(quote(name) for name in names)
        digest=hashlib.sha256();count=0
        for row in connection.exec_driver_sql(f'SELECT {fields} FROM {quote(table)} ORDER BY {fields}'):
            digest.update(json.dumps(list(row),default=lambda value: {'blob':value.hex()} if isinstance(value,bytes) else str(value),
                                     separators=(',',':'),ensure_ascii=True).encode())
            digest.update(b'\n');count+=1
        result[table]={'columns':names,'count':count,'sha256':digest.hexdigest()}
    return result


def verify_backup(source,output_root=None,*,adopt_legacy=False):
    source=Path(source).resolve(strict=True)
    if not source.is_file():raise ValueError('Choose a SQLite backup file')
    original_hash=file_hash(source)
    root=Path(output_root or ROOT/'var/restore_checks').resolve()
    root.mkdir(parents=True,exist_ok=True)
    work=root/('restore-'+uuid.uuid4().hex);work.mkdir()
    target=work/'restored.sqlite'
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as current:
        with sqlite3.connect(target) as restored:
            current.backup(restored)
            if restored.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('Restored backup integrity check failed')
            if restored.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('Restored backup contains broken references')
    bind=create_engine('sqlite:///'+target.as_posix())
    try:
        with bind.connect() as connection:before=snapshot(connection)
        if 'payments' not in before:raise ValueError('Backup is not a RecoverAI database')
        migrate_database(bind,adopt_legacy=adopt_legacy,backup_directory=work/'migration_backups')
        with bind.connect() as connection:
            after=snapshot(connection,{table:entry['columns'] for table,entry in before.items()})
            if before!=after:raise ValueError('Migration changed existing backup records; review required')
            if connection.exec_driver_sql('PRAGMA integrity_check').scalar()!='ok':raise ValueError('Migrated copy integrity check failed')
            if connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:raise ValueError('Migrated copy has broken references')
        if file_hash(source)!=original_hash:raise ValueError('Backup source changed during verification')
        report={'status':'passed','schema':schema_status(bind),'source_unchanged':True,
                'existing_records_unchanged':True,'table_counts':{table:entry['count'] for table,entry in before.items()},
                'scope':'Isolated SQLite restore and schema upgrade; no provider calls or service startup'}
        (work/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report,work/'report.json'
    finally:bind.dispose()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup',type=Path)
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--adopt-legacy',action='store_true')
    args=parser.parse_args(argv)
    try:
        report,path=verify_backup(args.backup,args.output_root,adopt_legacy=args.adopt_legacy)
        print(json.dumps({'status':report['status'],'source_unchanged':True,'report':str(path)}))
        return 0
    except Exception:
        print(json.dumps({'status':'failed','reason':'Restore check did not pass. Keep the source backup and inspect the isolated copy; no configured database was overwritten.'}))
        return 1


if __name__=='__main__':raise SystemExit(main())

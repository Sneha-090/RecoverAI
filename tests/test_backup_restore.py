import hashlib
import sqlite3
import pytest
from sqlalchemy import create_engine,text
from alembic import command
from app.db.schema import migration_config
from scripts.verify_backup import verify_backup


def test_real_restore_upgrades_copy_retains_records_and_never_touches_source(tmp_path):
    source=tmp_path/'backup.sqlite'
    engine=create_engine('sqlite:///'+source.as_posix())
    with engine.begin() as c:
        command.upgrade(migration_config(c),'0001')
        c.execute(text("INSERT INTO payments (payment_id,order_id,amount,status) VALUES ('pay_retained','order_kept',499,'failed')"))
    engine.dispose()
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    report,path=verify_backup(source,tmp_path/'checks')
    assert report['status']=='passed' and report['schema']['is_current']
    assert report['table_counts']['payments']==1
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    with sqlite3.connect(path.parent/'restored.sqlite') as restored:
        assert restored.execute('SELECT amount,recovery_stop_reason FROM payments').fetchone()==(499,None)
        assert restored.execute('SELECT payment_id FROM original_order_recoveries').fetchone()==('pay_retained',)
    with sqlite3.connect(source) as old:
        assert old.execute('SELECT version_num FROM alembic_version').fetchone()==('0001',)
    # Each run retains a new copy; no prior drill or source is overwritten.
    _,second=verify_backup(source,tmp_path/'checks')
    assert second!=path and path.exists()


def test_foreign_database_is_refused_and_source_is_unchanged(tmp_path):
    path=tmp_path/'foreign.sqlite'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE unrelated (value TEXT)')
    original=path.read_bytes()
    with pytest.raises(ValueError,match='not a RecoverAI'):
        verify_backup(path,tmp_path/'checks')
    assert path.read_bytes()==original

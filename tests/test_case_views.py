from datetime import datetime,timedelta
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Payment,AuditLog
from app.services.case_views import find_live_cases,case_timeline


def test_literal_search_status_source_limit_and_safe_timeline():
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add_all([Payment(payment_id='pay_A',amount=100,status='failed'),
                    Payment(payment_id='pay_B',amount=100,status='recovered'),
                    Payment(payment_id='sim_A',amount=100,status='failed')])
        now=datetime.utcnow()
        db.add_all([
            AuditLog(payment_id='pay_A',timestamp=now,event_type='recovered',
                     payload_json=json.dumps({'provider_id':'plink_Valid','email':'PRIVATE','secret':'PRIVATE'})),
            AuditLog(payment_id='pay_A',timestamp=now-timedelta(seconds=1),event_type='executed',
                     reason='PRIVATE',payload_json='not valid json'),
        ]);db.commit()
        assert [p.payment_id for p in find_live_cases(db,'B','recovered')]==['pay_B']
        assert find_live_cases(db,'%')==[]
        assert len(find_live_cases(db,limit=1))==1
        rows=case_timeline(db,'pay_A')
        assert [r['Event'] for r in rows]==['Recovery checkout created','Recovery verified']
        assert rows[-1]['Provider reference']=='plink_Valid'
        assert 'PRIVATE' not in json.dumps(rows)
        assert len(case_timeline(db,'pay_A',limit=1))==1
    engine.dispose()

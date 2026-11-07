"""Run real recovery services with a fake provider and a fresh isolated database.

The CLI replaces credentials in its own process and blocks outbound networking.
It never connects to the configured merchant DB or changes the local .env.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import sys
from pathlib import Path
import uuid
from unittest.mock import patch


from app.services.artifact_hashes import text_sha256


ROOT = Path(__file__).resolve().parents[1]


def configure_isolated_environment(database):
    values = {'DATABASE_URL':f'sqlite:///{database.as_posix()}',
        'RAZORPAY_KEY_ID':'rzp_test_offline_demo', 'RAZORPAY_KEY_SECRET':'offline_demo_not_a_real_secret',
        'RAZORPAY_WEBHOOK_SECRET':'offline_demo_signature_fixture',
        'OPERATOR_USERNAME':'offline_demo', 'OPERATOR_PASSWORD_HASH':'offline_demo_no_login',
        'HUMAN_REVIEW_TIMEOUT_HOURS':'24','MAX_RECOVERY_WINDOW_DAYS':'14','MAX_RETRY_ATTEMPTS':'3',
        'RETRY_COOLING_OFF_HOURS':'4','ACTION_COST_RETRY':'5','ACTION_COST_PAYMENT_LINK':'15',
        'ACTION_COST_ALT_METHOD':'10','SCORE_FLOOR':'0','MIN_ACTION_MARGIN_RATIO':'0.02','HUMAN_REVIEW_AMOUNT_THRESHOLD':'50000',
        'ALLOWED_ORIGINS':'[]','API_BASE_URL':'http://127.0.0.1:8001'}
    os.environ.update(values)


def run_scenarios(database):
    if 'app.config' in sys.modules or 'app.db.session' in sys.modules:
        raise RuntimeError('Run the offline demo in a fresh process; existing app configuration must not be reused')
    if database.exists():
        raise RuntimeError('Refusing to reuse an existing database')
    configure_isolated_environment(database)
    # These imports must follow environment isolation.
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import Base, engine, SessionLocal
    from app.models.models import (Payment, Action, AuditLog, Outcome, RecoveryIntent,
                                   RecoveryReservation, WebhookInbox, WebhookReceipt)
    from app.services.razorpay_client import client
    from app.services.execution import observe_outcome, human_review_action
    from app.services.reconciliation import check_reconciliation_status, reconcile_verified_success
    from app.services.webhook_replay import replay_batch
    from app.services.escalation import expire_overdue_reviews
    from scripts.demo_provider import DemoProvider
    Base.metadata.create_all(engine)
    fake, scenarios = DemoProvider(), []

    def post(payload, event_id, valid=True):
        body = json.dumps(payload).encode()
        signature = hmac.new(os.environ['RAZORPAY_WEBHOOK_SECRET'].encode(), body, hashlib.sha256).hexdigest()
        with TestClient(app, raise_server_exceptions=False) as transport:
            response = transport.post('/webhooks/razorpay',content=body,headers={
                'X-Razorpay-Event-Id':event_id,'X-Razorpay-Signature':signature if valid else 'invalid'})
        return response

    def event(name, entity):
        return {'event':name,'payload':{'payment':{'entity':entity}}}

    def failure(payment_id, amount=499):
        entity = fake.failed_payment(payment_id, amount)
        return post(event('payment.failed',entity), 'evt_'+payment_id), entity

    def approve(payment_id, chosen=None):
        with SessionLocal() as db:
            review = db.query(Action).filter_by(payment_id=payment_id,review_status='pending').first()
            if not review:
                return False
            result = human_review_action(db,payment_id,chosen or review.action_type)
            assert result['success'], result
            return True

    def finish(reference, event_id):
        response = post(event('payment.captured',fake.capture(reference)), event_id)
        assert response.status_code == 200, response.text
        assert response.json()['outcome']['status'] == 'recovered', response.text

    def record(name, payment_id, steps, before, **extra):
        with SessionLocal() as db:
            payment = db.get(Payment,payment_id)
            claim = db.get(RecoveryReservation,payment_id)
            audit = db.query(AuditLog).filter_by(payment_id=payment_id).order_by(AuditLog.id).all()
            scenarios.append({'name':name,'payment_id':payment_id,'steps':steps,
                'final_status':payment.status,'provider_creations':fake.creations-before,
                'outcomes':db.query(Outcome).filter_by(payment_id=payment_id).count(),
                'reservation':claim.state if claim else None,'audit_events':[row.event_type for row in audit],**extra})

    with ExitStack() as stack:
        # Any missed fake must fail locally, not fall through to an external API.
        original_connect = socket.socket.connect
        def local_ipc_only(sock, address):
            # Windows asyncio implements socketpair with a loopback connection.
            # External sockets and all real HTTP requests remain prohibited.
            if isinstance(address, tuple):
                try:
                    if ipaddress.ip_address(address[0]).is_loopback:
                        return original_connect(sock, address)
                except ValueError:
                    pass
            raise RuntimeError('External networking is disabled in offline demo')
        stack.enter_context(patch('socket.socket.connect', new=local_ipc_only))
        for target in ['socket.create_connection','requests.sessions.Session.request']:
            stack.enter_context(patch(target, side_effect=RuntimeError('Outbound networking is disabled in offline demo')))
        for resource, method, replacement in [
            (client.order,'create',fake.create_order),(client.order,'fetch',fake.fetch_order),
            (client.order,'payments',fake.order_payments),(client.payment_link,'create',fake.create_link),
            (client.payment_link,'fetch',fake.fetch_link),(client.payment,'fetch',fake.fetch_payment)]:
            stack.enter_context(patch.object(resource,method,side_effect=replacement))

        before = fake.creations
        response, entity = failure('pay_DemoNormal')
        assert response.status_code == 200 and response.json()['executed'] is True, response.text
        reference = fake.last_created
        duplicate = post(event('payment.failed',entity),'evt_pay_DemoNormal')
        assert duplicate.json()['status'] == 'already_processed'
        invalid = post(event('payment.failed',entity),'evt_invalid_demo',valid=False)
        assert invalid.status_code == 400
        with SessionLocal() as db:
            pending = observe_outcome(db,db.get(Payment,'pay_DemoNormal'))
            assert pending['status'] == 'awaiting_outcome'
        assert fake.creations-before == 1
        finish(reference,'evt_normal_captured')
        record('Signed failure, duplicate protection and verified recovery','pay_DemoNormal',[
            'A signed failure reaches the real webhook route and ML/policy pipeline.',
            'The same event is delivered twice; the second delivery is acknowledged without another resource.',
            'An invalid signature is rejected with HTTP 400.',
            'An unpaid resource stays pending; no follow-up resource is created.',
            'A verified captured event settles the original case once.'],before,
            duplicate_status=duplicate.json()['status'],invalid_signature_http=invalid.status_code)

        before = fake.creations
        response, _ = failure('pay_DemoApproval',60000)
        assert response.json()['decision_type'] == 'human_review'
        assert fake.creations == before
        assert approve('pay_DemoApproval')
        finish(fake.last_created,'evt_approval_captured')
        record('High-value recovery requires human approval','pay_DemoApproval',[
            'A high-value case enters review; no provider resource exists yet.',
            'The demo operator explicitly approves an untried recovery action.',
            'Only then is one simulated provider resource created.',
            'Captured payment evidence closes the original case.'],before)

        before = fake.creations
        fake.lose_next_response = True
        response, _ = failure('pay_DemoLostResponse')
        assert response.status_code == 500
        reference = fake.last_created
        with SessionLocal() as db:
            assert db.get(RecoveryReservation,'pay_DemoLostResponse').state == 'needs_reconciliation'
            intent = db.query(RecoveryIntent).filter_by(payment_id='pay_DemoLostResponse').one()
            key = 'intent:'+intent.id
            fake.capture(reference)
            evidence = check_reconciliation_status(db,'pay_DemoLostResponse',key,reference[1])
            assert evidence['result'] == 'success'
            result = reconcile_verified_success(db,'pay_DemoLostResponse',key,'offline_demo_operator',reference[1])
            assert result['status'] == 'recovered', result
            assert db.get(WebhookReceipt,'evt_pay_DemoLostResponse').state == 'needs_reconciliation'
        assert fake.creations-before == 1
        record('Lost creation response is reconciled without repeating payment','pay_DemoLostResponse',[
            'The provider accepts creation, then the simulated response is lost.',
            'The case is blocked for reconciliation; automatic creation is not retried.',
            'The operator checks the existing resource; intent notes, amount and currency must match.',
            'Fresh verification settles the case with one resource; the uncertain webhook is not forcibly replayed.'],before)

        before = fake.creations
        response, _ = failure('pay_DemoLateCapture',60000)
        assert response.json()['decision_type'] == 'human_review'
        assert approve('pay_DemoLateCapture','retry')
        old_reference = fake.last_created
        assert old_reference[0] == 'order'
        fake.fail_attempt(old_reference)
        with SessionLocal() as db:
            observe_outcome(db,db.get(Payment,'pay_DemoLateCapture'))
        approve('pay_DemoLateCapture')
        current_reference = fake.last_created
        assert current_reference != old_reference
        finish(old_reference,'evt_late_old_capture')
        record('Late success is matched to the older retry','pay_DemoLateCapture',[
            'The operator approves an initial retry order.',
            'That attempt reports failure, and a different recovery action is selected/approved.',
            'A delayed capture arrives for the old order.',
            'The old execution result is upgraded to success; no extra recovery action starts.'],before,
            old_provider_id=old_reference[1],new_provider_id=current_reference[1])

        before = fake.creations
        response, _ = failure('pay_DemoExpiry',60000)
        assert response.json()['decision_type'] == 'human_review'
        with SessionLocal() as db:
            review = db.query(Action).filter_by(payment_id='pay_DemoExpiry',review_status='pending').one()
            expired = expire_overdue_reviews(db,now=review.review_deadline+timedelta(seconds=1))
            assert len(expired) == 1
        assert fake.creations == before
        record('Review deadline closes a case without a risky action','pay_DemoExpiry',[
            'A high-value failure waits for human review.',
            'The fixture advances the review deadline; no approval is supplied.',
            'The real maintenance service expires the review, closes the failed case and clears its review claim.',
            'Zero provider resources are created.'],before)

        before = fake.creations
        early_id = 'evt_early_demo_capture'
        early_response = []
        def capture_before_response(reference):
            payload = event('payment.captured',fake.capture(reference))
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(post,payload,early_id).result(timeout=15)
            early_response.append(response.json()['status'])
            assert response.status_code == 200 and response.json()['status'] == 'waiting_for_execution'
        fake.on_create = capture_before_response
        response, _ = failure('pay_DemoEarlyCapture')
        assert response.status_code == 200
        with SessionLocal() as db:
            assert db.get(WebhookInbox,early_id).state == 'waiting_for_execution'
        replay = replay_batch(event_id=early_id)
        assert replay['processed'] == 1 and replay['errors'] == 0, replay
        record('Early capture survives until execution persistence','pay_DemoEarlyCapture',[
            'A signed capture arrives before the creation response and execution audit are saved.',
            'The verified event is durably stored as waiting for execution.',
            'The original creation response finishes and binds the execution.',
            'The real replay worker matches the event and settles once.'],before,
            early_status=early_response[0],replay_processed=replay['processed'])
    engine.dispose()
    return {'scope':'OFFLINE SIMULATION: real app services, fake provider, isolated SQLite, outbound network blocked',
        'not_a_live_provider_test':True,'scenarios':scenarios,'passed':len(scenarios),
        'network_policy':'External sockets and HTTP blocked; local loopback IPC allowed for Windows asyncio',
        'demo_code_sha256':text_sha256(__file__),
        'source_fingerprints':{name:text_sha256(ROOT/name) for name in [
            'app/api/webhooks.py','app/services/execution.py','app/services/policy.py',
            'app/services/diagnosis.py','app/services/decision.py','app/services/ml_service.py',
            'app/services/reservations.py','app/services/escalation.py','app/services/reconciliation.py',
            'app/services/webhook_inbox.py','app/services/webhook_replay.py',
            'scripts/demo_provider.py','scripts/render_demo_html.py']},
        'model_sha256':hashlib.sha256((ROOT/'ML/recovery_model.joblib').read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports')
    parser.add_argument('--work-dir',type=Path,default=ROOT/'.venv/demo_runs')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True,exist_ok=True)
    database = args.work_dir/f'offline_{uuid.uuid4().hex}.sqlite'
    if database.exists():
        raise SystemExit('Refusing to reuse an existing database')
    report = run_scenarios(database)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'offline_demo.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    lines = ['# Offline recovery walkthrough','',report['scope'],'',
             'No merchant database, .env file or external payment is changed. Each run creates a new SQLite fixture.','']
    for index, scenario in enumerate(report['scenarios'],1):
        lines += [f"## {index}. {scenario['name']}",'',*['- '+step for step in scenario['steps']],
            '',f"Result: **{scenario['final_status']}**; simulated provider creations: {scenario['provider_creations']}; stored outcomes: {scenario['outcomes']}.",'']
    (args.output_dir/'OFFLINE_DEMO.md').write_text('\n'.join(lines),encoding='utf-8')
    from scripts.render_demo_html import render_demo_html
    (args.output_dir/'offline_demo.html').write_text(render_demo_html(report),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'scope':report['scope'],'database':str(database),
                      'report':str(args.output_dir/'OFFLINE_DEMO.md')},indent=2))


if __name__ == '__main__':
    main()

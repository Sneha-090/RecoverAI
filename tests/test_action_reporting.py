from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Action, Diagnosis, Payment
from app.services.action_reporting import build_action_report


@pytest.fixture
def report_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add_all([
            Payment(payment_id='pay_approved', amount=499, status='recovered'),
            Payment(payment_id='pay_auto', amount=100, status='failed'),
            Payment(payment_id='pay_unprocessed', amount=200, status='failed'),
            Payment(payment_id='sim_fixture', amount=9000, status='recovered'),
            Payment(payment_id='payXnot_provider', amount=99999, status='recovered'),
        ])
        db.add_all([
            Diagnosis(payment_id='pay_approved', cause='bank_declined'),
            Diagnosis(payment_id='pay_auto', cause='network_error'),
            Diagnosis(payment_id='sim_fixture', cause='insufficient_funds'),
        ])
        now = datetime.utcnow()
        db.add_all([
            Action(payment_id='pay_approved', action_type='alt_method', decision_type='auto',
                   chosen_at=now, reason='human-approved action (original ML recommendation: payment_link)'),
            Action(payment_id='pay_approved', action_type='payment_link', decision_type='human_review',
                   chosen_at=now-timedelta(minutes=1), review_status='actioned'),
            Action(payment_id='pay_auto', action_type='retry', decision_type='auto'),
            Action(payment_id='sim_fixture', action_type='alt_method', decision_type='auto'),
        ])
        db.commit()
        yield db
    engine.dispose()


def test_first_decision_and_execution_are_distinct_and_chronological(report_db):
    report = build_action_report(report_db)
    assert report['cases'] == 3 and report['recovered_cases'] == 1
    assert report['recovered_amount'] == 499
    assert report['first_decisions'] == 2 and report['executions'] == 2
    assert report['cases_without_decision'] == 1
    rows = {row['Action']: row for row in report['distribution']}
    assert rows['payment_link']['First recorded decisions'] == 1
    assert rows['payment_link']['Recorded executions'] == 0
    assert rows['alt_method']['First recorded decisions'] == 0
    assert rows['alt_method']['Recorded executions'] == 1
    assert rows['alt_method']['Human-approved executions'] == 1
    assert rows['retry']['Share of first decisions'] == .5


def test_sources_do_not_mix_and_prefix_is_literal(report_db):
    report = build_action_report(report_db, 'Simulation')
    assert report['cases'] == 1 and report['recovered_amount'] == 9000
    assert report['available_causes'] == ['insufficient_funds']
    assert report['executions'] == 1


def test_cause_filter_changes_the_denominator_and_keeps_available_choices(report_db):
    report = build_action_report(report_db, cause='network_error')
    assert report['cases'] == report['first_decisions'] == report['executions'] == 1
    rows = {row['Action']: row for row in report['distribution']}
    assert rows['retry']['Share of first decisions'] == 1
    assert set(report['available_causes']) == {'bank_declined','network_error','Not recorded'}
    assert report['by_cause'][0]['Recorded cause'] == 'network_error'


def test_manual_assessment_is_visible_but_never_an_execution(report_db):
    report_db.add(Action(payment_id='pay_unprocessed', action_type='manual_assessment',
                         decision_type='human_review', review_status='pending'))
    report_db.commit()
    report = build_action_report(report_db)
    assert report['pending_review_cases'] == 1
    row = next(row for row in report['distribution'] if row['Action']=='manual_assessment')
    assert row['First recorded decisions'] == 1 and row['Recorded executions'] == 0
    assert sum(row['First recorded decisions'] for row in report['distribution']) == report['first_decisions']


def test_empty_filter_has_zero_counts_without_losing_scope(report_db):
    report = build_action_report(report_db, cause='no_such_cause')
    assert report['cases'] == report['first_decisions'] == report['executions'] == 0
    assert report['recovered_amount'] == 0
    assert all(row['Share of first decisions']==0 for row in report['distribution'])
    assert report['by_cause'] == []


def test_unsupported_scope_is_rejected(report_db):
    with pytest.raises(ValueError):
        build_action_report(report_db, 'mix_everything')

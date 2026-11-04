import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.models import AuditLog, Action, Payment, Outcome
from app.services.execution import (
    _get_last_execution_payload,
    observe_outcome,
)
from app.services.execution_records import amount_paise, resolve_execution
from app.models.models import RecoveryExecution, ExecutionOutcome, RecoveryReservation
from app.services.execution_records import record_execution

@pytest.fixture
def db_session():
    # Temporary in-memory database.
    # Real recoverai.db is NOT touched.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_human_approved_execution_payload_is_found(db_session):
    payload = {
        "type": "order",
        "order_id": "order_human_123",
    }

    audit = AuditLog(
        payment_id="pay_123",
        event_type="human_approved_executed",
        payload_json=json.dumps(payload),
    )

    db_session.add(audit)
    db_session.commit()

    result = _get_last_execution_payload(
        db_session,
        "pay_123",
    )

    assert result == payload


def test_execution_amount_avoids_binary_float_truncation():
    assert amount_paise(19.9) == 1990


def test_legacy_execution_import_requires_an_unambiguous_action(db_session):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    payment = Payment(payment_id="pay_legacy", amount=19.9, status="failed")
    db_session.add(payment)
    action = Action(payment_id=payment.payment_id, action_type="retry",
                    decision_type="auto", chosen_at=now)
    db_session.add(action)
    db_session.add(AuditLog(payment_id=payment.payment_id, event_type="executed",
        timestamp=now + timedelta(seconds=1),
        payload_json=json.dumps({"type": "order", "order_id": "order_legacy"})))
    db_session.commit()
    first, payload = resolve_execution(db_session, payment, order_id="order_legacy")
    second, _ = resolve_execution(db_session, payment, order_id="order_legacy")
    assert first.id == second.id
    assert first.action_id == action.id
    assert first.amount_paise == 1990
    assert payload["order_id"] == "order_legacy"
    assert db_session.query(RecoveryExecution).count() == 1


def test_ambiguous_legacy_actions_are_not_guessed(db_session):
    payment = Payment(payment_id="pay_ambiguous", amount=100, status="failed")
    db_session.add(payment)
    for kind in ["retry", "payment_link"]:
        db_session.add(Action(payment_id=payment.payment_id, action_type=kind, decision_type="auto"))
    db_session.commit()
    db_session.add(AuditLog(payment_id=payment.payment_id, event_type="executed",
        payload_json=json.dumps({"type": "order", "order_id": "order_ambiguous"})))
    db_session.commit()
    execution, _ = resolve_execution(db_session, payment, order_id="order_ambiguous")
    assert execution is None
    assert db_session.query(RecoveryExecution).count() == 0


def test_latest_human_approved_execution_wins_over_old_auto_execution(db_session):
    old_payload = {
        "type": "order",
        "order_id": "old_retry_order_123",
    }

    new_payload = {
        "type": "order",
        "order_id": "human_retry_order_456",
    }

    old_audit = AuditLog(
        payment_id="pay_456",
        event_type="executed",
        payload_json=json.dumps(old_payload),
    )

    db_session.add(old_audit)
    db_session.commit()

    new_audit = AuditLog(
        payment_id="pay_456",
        event_type="human_approved_executed",
        payload_json=json.dumps(new_payload),
    )

    db_session.add(new_audit)
    db_session.commit()

    result = _get_last_execution_payload(
        db_session,
        "pay_456",
    )

    assert result == new_payload
    assert result["order_id"] == "human_retry_order_456"

   


def test_human_approved_retry_outcome_uses_latest_action(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_human_outcome_123",
        amount=5000,
        status="failed",
    )
    db_session.add(payment)

    action = Action(
        payment_id="pay_human_outcome_123",
        action_type="retry",
        decision_type="auto",
    )
    db_session.add(action)
    db_session.commit()

    payload = {
        "type": "order",
        "order_id": "human_recovery_order_123",
    }

    audit = AuditLog(
        payment_id="pay_human_outcome_123",
        event_type="human_approved_executed",
        payload_json=json.dumps(payload),
    )
    db_session.add(audit)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.execution._check_real_outcome",
        lambda payload: "success",
    )

    result = observe_outcome(db_session, payment)

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_human_outcome_123"
        )
        .first()
    )

    assert result["status"] == "recovered"
    assert payment.status == "recovered"
    assert outcome is not None
    assert outcome.action_type == "retry"
    assert outcome.observed_result == "success"

def test_payment_link_success_marks_original_payment_recovered(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_payment_link_success_123",
        amount=6000,
        status="failed",
    )

    action = Action(
        payment_id="pay_payment_link_success_123",
        action_type="payment_link",
        decision_type="auto",
        chosen_at=datetime.utcnow() - timedelta(seconds=1),
    )

    audit = AuditLog(
        payment_id="pay_payment_link_success_123",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "payment_link",
                "payment_link_id": "plink_success_123",
                "short_url": "https://rzp.io/rzp/success123",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(action)
    db_session.add(audit)
    db_session.commit()

    def fake_payment_link_fetch(payment_link_id):
        assert payment_link_id == "plink_success_123"
        return {
            "id": "plink_success_123",
            "status": "paid",
            "amount": 600000, "amount_paid": 600000, "currency": "INR",
        }

    monkeypatch.setattr(
        "app.services.execution.client.payment_link.fetch",
        fake_payment_link_fetch,
    )

    result = observe_outcome(
        db_session,
        payment,
    )

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_payment_link_success_123"
        )
        .first()
    )

    assert result["status"] == "recovered"
    assert payment.status == "recovered"
    assert outcome is not None
    assert outcome.action_type == "payment_link"
    assert outcome.observed_result == "success"
def test_payment_link_failed_does_not_mark_payment_recovered(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_payment_link_failed_123",
        amount=6000,
        status="failed",
    )

    action = Action(
        payment_id="pay_payment_link_failed_123",
        action_type="payment_link",
        decision_type="auto",
        chosen_at=datetime.utcnow() - timedelta(seconds=1),
    )

    audit = AuditLog(
        payment_id="pay_payment_link_failed_123",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "payment_link",
                "payment_link_id": "plink_failed_123",
                "short_url": "https://rzp.io/rzp/failed123",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(action)
    db_session.add(audit)
    db_session.commit()

    def fake_payment_link_fetch(payment_link_id):
        assert payment_link_id == "plink_failed_123"
        return {
            "id": "plink_failed_123",
            "status": "expired",
        }

    monkeypatch.setattr(
        "app.services.execution.client.payment_link.fetch",
        fake_payment_link_fetch,
    )

    # Force the next decision so the test does not make a real
    # Razorpay order/payment-link call.
    monkeypatch.setattr(
        "app.services.execution._execute_action",
        lambda db, payment: {
            "chosen_action": None,
            "decision_type": "skip",
            "reason": "no remaining action for test",
            "executed": False,
        },
    )

    result = observe_outcome(
        db_session,
        payment,
    )

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_payment_link_failed_123"
        )
        .first()
    )

    assert result["status"] == "closed_unrecovered"
    assert payment.status == "closed_unrecovered"
    assert outcome is not None
    assert outcome.action_type == "payment_link"
    assert outcome.observed_result == "failed"

def test_alt_method_payment_link_success_marks_payment_recovered(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_alt_method_success_123",
        amount=6000,
        status="failed",
    )

    action = Action(
        payment_id="pay_alt_method_success_123",
        action_type="alt_method",
        decision_type="auto",
        chosen_at=datetime.utcnow() - timedelta(seconds=1),
    )

    audit = AuditLog(
        payment_id="pay_alt_method_success_123",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "payment_link",
                "payment_link_id": "plink_alt_success_123",
                "short_url": "https://rzp.io/rzp/alt123",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(action)
    db_session.add(audit)
    db_session.commit()

    def fake_payment_link_fetch(payment_link_id):
        assert payment_link_id == "plink_alt_success_123"
        return {
            "id": "plink_alt_success_123",
            "status": "paid",
            "amount": 600000, "amount_paid": 600000, "currency": "INR",
        }

    monkeypatch.setattr(
        "app.services.execution.client.payment_link.fetch",
        fake_payment_link_fetch,
    )

    result = observe_outcome(
        db_session,
        payment,
    )

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_alt_method_success_123"
        )
        .first()
    )

    assert result["status"] == "recovered"
    assert payment.status == "recovered"
    assert outcome is not None
    assert outcome.action_type == "alt_method"
    assert outcome.observed_result == "success"


def stored_attempt(db, payment, kind, resource_id, chosen_at, action_type=None):
    action = Action(payment_id=payment.payment_id, action_type=action_type or (
        "retry" if kind == "order" else "payment_link"),
        decision_type="auto", chosen_at=chosen_at)
    payload = {"type": kind, "order_id" if kind == "order" else "payment_link_id": resource_id}
    audit = AuditLog(payment_id=payment.payment_id, event_type="executed",
                     timestamp=chosen_at + timedelta(seconds=1), payload_json=json.dumps(payload))
    db.add_all([action, audit])
    db.flush()
    row = record_execution(db, payment, action, audit, payload)
    db.commit()
    return row


@pytest.mark.parametrize("kind", ["order", "payment_link"])
@pytest.mark.parametrize("case_state", ["failed", "closed_unrecovered", "pending_review"])
def test_late_success_settles_exact_old_execution(db_session, monkeypatch, kind, case_state):
    from unittest.mock import Mock
    payment = Payment(payment_id="pay_late", amount=499, status=(
        "failed" if case_state == "pending_review" else case_state))
    db_session.add(payment)
    old = stored_attempt(db_session, payment, kind, "old_resource", datetime.utcnow() - timedelta(hours=2))
    previous = Outcome(payment_id=payment.payment_id, action_type=db_session.get(Action, old.action_id).action_type,
                       observed_result="failed", observed_at=datetime.utcnow() - timedelta(hours=1))
    db_session.add(previous)
    db_session.flush()
    db_session.add(ExecutionOutcome(execution_id=old.id, outcome_id=previous.id))
    current = stored_attempt(db_session, payment, "payment_link", "new_resource", datetime.utcnow())
    if case_state == "pending_review":
        review = Action(payment_id=payment.payment_id, action_type="alt_method", decision_type="human_review",
                        review_status="pending")
        db_session.add(review)
        db_session.add(RecoveryReservation(payment_id=payment.payment_id, owner="review", state="pending_review"))
    elif case_state == "failed":
        db_session.add(RecoveryReservation(payment_id=payment.payment_id, owner="waiting", state="awaiting_outcome"))
    db_session.commit()

    if kind == "order":
        provider = Mock(return_value={"items": [{"id": "pay_capture", "status": "captured",
                                                  "amount": 49900, "currency": "INR"}]})
        monkeypatch.setattr("app.services.execution.client.order.payments", provider)
    else:
        provider = Mock(return_value={"id": "old_resource", "status": "paid", "amount": 49900,
                                      "amount_paid": 49900, "currency": "INR"})
        monkeypatch.setattr("app.services.execution.client.payment_link.fetch", provider)
    advance = Mock(side_effect=AssertionError("Late success must not create another recovery action"))
    monkeypatch.setattr("app.services.execution._execute_action", advance)
    expected = {"expected_order_id" if kind == "order" else "expected_payment_link_id": "old_resource"}
    assert observe_outcome(db_session, payment, **expected)["execution_id"] == old.id
    assert payment.status == "recovered"
    assert db_session.query(Outcome).count() == 1
    assert db_session.get(Outcome, previous.id).observed_result == "success"
    assert db_session.get(ExecutionOutcome, current.id) is None
    assert db_session.get(RecoveryReservation, payment.payment_id) is None
    if case_state == "pending_review":
        db_session.refresh(review)
        assert review.review_status.value == "expired"
    assert observe_outcome(db_session, payment, **expected)["status"] == "recovered"
    assert provider.call_count == 1
    advance.assert_not_called()


@pytest.mark.parametrize("provider_state", ["failed", "pending"])
@pytest.mark.parametrize("waiting_state", ["awaiting_outcome", "pending_review"])
def test_old_failure_or_pending_never_advances_current_attempt(db_session, monkeypatch, provider_state, waiting_state):
    from unittest.mock import Mock
    payment = Payment(payment_id="pay_old_failure", amount=100, status="failed")
    db_session.add(payment)
    old = stored_attempt(db_session, payment, "order", "order_old", datetime.utcnow() - timedelta(hours=2))
    stored_attempt(db_session, payment, "payment_link", "plink_new", datetime.utcnow())
    db_session.add(RecoveryReservation(payment_id=payment.payment_id, owner="waiting", state=waiting_state))
    db_session.commit()
    monkeypatch.setattr("app.services.execution.client.order.payments", lambda _: {
        "items": [{"status": "failed"}] if provider_state == "failed" else []})
    advance = Mock(side_effect=AssertionError("Old event must not start a new action"))
    monkeypatch.setattr("app.services.execution._execute_action", advance)
    for _ in range(2):
        assert observe_outcome(db_session, payment, expected_order_id="order_old")["status"] == waiting_state
        assert db_session.get(RecoveryReservation, payment.payment_id).state == waiting_state
    assert db_session.query(Outcome).count() == (1 if provider_state == "failed" else 0)
    if provider_state == "failed":
        assert db_session.get(ExecutionOutcome, old.id) is not None
    advance.assert_not_called()


@pytest.mark.parametrize("kind", ["order", "payment_link"])
@pytest.mark.parametrize("bad_field,bad_value", [("amount", 1), ("currency", "USD"), ("currency", None)])
def test_mismatched_capture_stays_unrecovered(db_session, monkeypatch, kind, bad_field, bad_value):
    payment = Payment(payment_id="pay_mismatch", amount=499, status="failed")
    db_session.add(payment)
    stored_attempt(db_session, payment, kind, "resource", datetime.utcnow())
    resource = {"id": "resource", "status": "captured" if kind == "order" else "paid",
                "amount": 49900, "currency": "INR", "amount_paid": 49900}
    resource[bad_field] = bad_value
    if kind == "order":
        monkeypatch.setattr("app.services.execution.client.order.payments", lambda _: {"items": [resource]})
    else:
        monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda _: resource)
    with pytest.raises(ValueError, match="match execution"):
        observe_outcome(db_session, payment)
    db_session.refresh(payment)
    assert payment.status == "failed"
    assert db_session.query(Outcome).count() == 0
    assert db_session.get(RecoveryReservation, payment.payment_id).state == "needs_reconciliation"


@pytest.mark.parametrize("field,value", [("id", "plink_other"), ("amount_paid", 1), ("amount_paid", None)])
def test_paid_link_requires_matching_resource_and_full_payment(db_session, monkeypatch, field, value):
    payment = Payment(payment_id="pay_bad_link", amount=499, status="failed")
    db_session.add(payment)
    stored_attempt(db_session, payment, "payment_link", "plink_expected", datetime.utcnow())
    link = {"id": "plink_expected", "status": "paid", "amount": 49900,
            "currency": "INR", "amount_paid": 49900}
    link[field] = value
    monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda _: link)
    with pytest.raises(ValueError):
        observe_outcome(db_session, payment)
    assert db_session.query(Outcome).count() == 0
    assert db_session.get(RecoveryReservation, payment.payment_id).state == "needs_reconciliation"


def test_same_action_type_has_independent_outcomes_and_late_success_upgrades_only_its_result(db_session, monkeypatch):
    payment = Payment(payment_id="pay_repeat_kind", amount=100, status="failed")
    db_session.add(payment)
    old = stored_attempt(db_session, payment, "payment_link", "plink_old", datetime.utcnow() - timedelta(hours=2))
    current = stored_attempt(db_session, payment, "payment_link", "plink_new", datetime.utcnow() - timedelta(hours=1))
    monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda key: {"id": key, "status": "expired"})
    monkeypatch.setattr("app.services.execution._execute_action", lambda *args: {
        "decision_type": "skip", "reason": "No more actions", "executed": False})
    observe_outcome(db_session, payment, expected_payment_link_id="plink_old")
    assert observe_outcome(db_session, payment, expected_payment_link_id="plink_new")["status"] == "closed_unrecovered"
    assert db_session.query(Outcome).count() == 2
    monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda key: {
        "id": key, "status": "paid", "amount": 10000, "amount_paid": 10000, "currency": "INR"})
    assert observe_outcome(db_session, payment, expected_payment_link_id="plink_old")["status"] == "recovered"
    assert db_session.get(Outcome, db_session.get(ExecutionOutcome, old.id).outcome_id).observed_result == "success"
    assert db_session.get(Outcome, db_session.get(ExecutionOutcome, current.id).outcome_id).observed_result == "failed"
    assert db_session.query(Outcome).count() == 2


def test_legacy_failure_is_adopted_instead_of_duplicated(db_session, monkeypatch):
    payment = Payment(payment_id="pay_legacy_result", amount=100, status="closed_unrecovered")
    db_session.add(payment)
    old = stored_attempt(db_session, payment, "order", "order_old", datetime.utcnow() - timedelta(hours=2))
    prior = Outcome(payment_id=payment.payment_id, action_type="retry", observed_result="failed",
                    observed_at=datetime.utcnow() - timedelta(hours=1))
    db_session.add(prior)
    db_session.commit()
    monkeypatch.setattr("app.services.execution.client.order.payments", lambda _: {
        "items": [{"status": "captured", "amount": 10000, "currency": "INR"}]})
    assert observe_outcome(db_session, payment, expected_order_id="order_old")["status"] == "recovered"
    assert db_session.get(ExecutionOutcome, old.id).outcome_id == prior.id
    assert db_session.query(Outcome).count() == 1
    assert db_session.get(Outcome, prior.id).observed_result == "success"


def test_legacy_pending_review_is_preserved_when_old_failure_arrives(db_session, monkeypatch):
    from unittest.mock import Mock
    payment = Payment(payment_id="pay_legacy_review", amount=100, status="failed")
    db_session.add(payment)
    stored_attempt(db_session, payment, "order", "order_old", datetime.utcnow() - timedelta(hours=2))
    db_session.add(Action(payment_id=payment.payment_id, action_type="payment_link",
                          decision_type="human_review", review_status="pending"))
    db_session.commit()
    monkeypatch.setattr("app.services.execution.client.order.payments", lambda _: {"items": [{"status": "failed"}]})
    advance = Mock(side_effect=AssertionError("Pending review must remain pending"))
    monkeypatch.setattr("app.services.execution._execute_action", advance)
    assert observe_outcome(db_session, payment, expected_order_id="order_old")["status"] == "pending_review"
    assert db_session.get(RecoveryReservation, payment.payment_id).state == "pending_review"
    advance.assert_not_called()


def test_unattributed_legacy_result_with_repeated_action_type_requires_reconciliation(db_session, monkeypatch):
    payment = Payment(payment_id="pay_ambiguous_result", amount=100, status="failed")
    db_session.add(payment)
    stored_attempt(db_session, payment, "payment_link", "plink_old", datetime.utcnow() - timedelta(hours=2))
    stored_attempt(db_session, payment, "payment_link", "plink_new", datetime.utcnow() - timedelta(hours=1))
    db_session.add(Outcome(payment_id=payment.payment_id, action_type="payment_link", observed_result="failed"))
    db_session.commit()
    monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda key: {
        "id": key, "status": "paid", "amount": 10000, "amount_paid": 10000, "currency": "INR"})
    assert observe_outcome(db_session, payment, expected_payment_link_id="plink_new")["status"] == "needs_reconciliation"
    assert payment.status == "failed"
    assert db_session.query(ExecutionOutcome).count() == 0
    assert db_session.query(Outcome).one().observed_result == "failed"

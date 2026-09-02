from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Payment, Action, DecisionType, ReviewStatus, AuditLog
from app.services.escalation import expire_overdue_reviews


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_overdue_review_gets_expired():
    db = make_session()
    payment = Payment(payment_id="pay_1", amount=60000, created_at=datetime.utcnow())
    db.add(payment)
    action = Action(
        payment_id="pay_1",
        action_type="retry",
        chosen_at=datetime.utcnow() - timedelta(hours=30),
        decision_type=DecisionType.human_review,
        review_deadline=datetime.utcnow() - timedelta(hours=6),  # 6h overdue
        review_status=ReviewStatus.pending,
    )
    db.add(action)
    db.commit()

    expired = expire_overdue_reviews(db)

    assert len(expired) == 1
    db.refresh(action)
    assert action.review_status == ReviewStatus.expired

    audit_entries = db.query(AuditLog).filter(AuditLog.event_type == "human_review_expired").all()
    assert len(audit_entries) == 1
    assert "no risky action auto-executed" in audit_entries[0].reason


def test_review_within_deadline_is_not_expired():
    db = make_session()
    payment = Payment(payment_id="pay_2", amount=60000, created_at=datetime.utcnow())
    db.add(payment)
    action = Action(
        payment_id="pay_2",
        action_type="payment_link",
        chosen_at=datetime.utcnow(),
        decision_type=DecisionType.human_review,
        review_deadline=datetime.utcnow() + timedelta(hours=10),  # still has time
        review_status=ReviewStatus.pending,
    )
    db.add(action)
    db.commit()

    expired = expire_overdue_reviews(db)

    assert len(expired) == 0
    db.refresh(action)
    assert action.review_status == ReviewStatus.pending


def test_already_actioned_review_is_ignored():
    db = make_session()
    payment = Payment(payment_id="pay_3", amount=60000, created_at=datetime.utcnow())
    db.add(payment)
    action = Action(
        payment_id="pay_3",
        action_type="alt_method",
        chosen_at=datetime.utcnow() - timedelta(hours=30),
        decision_type=DecisionType.human_review,
        review_deadline=datetime.utcnow() - timedelta(hours=6),
        review_status=ReviewStatus.actioned,  # human already acted
    )
    db.add(action)
    db.commit()

    expired = expire_overdue_reviews(db)

    assert len(expired) == 0
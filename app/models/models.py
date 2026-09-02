import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.orm import relationship

from app.db.session import Base


class DecisionType(str, enum.Enum):
    auto = "auto"
    human_review = "human_review"
    skip = "skip"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    actioned = "actioned"
    expired = "expired"


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(String, primary_key=True)
    order_id = Column(String, nullable=True)
    amount = Column(Float, nullable=False)
    payment_method = Column(String, nullable=True)
    razorpay_error_code = Column(String, nullable=True)
    razorpay_error_reason = Column(String, nullable=True)
    razorpay_state = Column(String, nullable=True)
    status = Column(String, nullable=False, default="failed")
    created_at = Column(DateTime, default=datetime.utcnow)

    customer_id = Column(String, ForeignKey("customers.customer_id"), nullable=True)

    diagnoses = relationship("Diagnosis", back_populates="payment")
    ml_predictions = relationship("MLPrediction", back_populates="payment")
    recovery_scores = relationship("RecoveryScore", back_populates="payment")
    actions = relationship("Action", back_populates="payment")
    outcomes = relationship("Outcome", back_populates="payment")


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=False)
    cause = Column(String, nullable=False)
    diagnosed_at = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="diagnoses")


class MLPrediction(Base):
    __tablename__ = "ml_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=False)
    action_type = Column(String, nullable=False)
    probability = Column(Float, nullable=False)
    predicted_at = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="ml_predictions")


class RecoveryScore(Base):
    __tablename__ = "recovery_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=False)
    action_type = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    cost_used = Column(Float, nullable=False)
    retry_eligible = Column(Boolean, nullable=False, default=True)

    # --- Module A additions ---
    eligibility_reason = Column(String, nullable=True)
    evaluated_at = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="recovery_scores")


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=False)
    action_type = Column(String, nullable=False)
    chosen_at = Column(DateTime, default=datetime.utcnow)
    decision_type = Column(SAEnum(DecisionType), nullable=False)

    # --- Module A addition ---
    reason = Column(String, nullable=True)

    escalated_at = Column(DateTime, nullable=True)
    review_deadline = Column(DateTime, nullable=True)
    review_status = Column(SAEnum(ReviewStatus), nullable=True)

    payment = relationship("Payment", back_populates="actions")


class Outcome(Base):
    __tablename__ = "outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=False)
    action_type = Column(String, nullable=False)
    observed_result = Column(String, nullable=False)
    observed_at = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="outcomes")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=True)
    reason = Column(String, nullable=True)


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(String, primary_key=True)
    previous_failures = Column(Integer, default=0)
    previous_recoveries = Column(Integer, default=0)
    avg_attempts = Column(Float, default=0.0)
    last_recovery_days_ago = Column(Integer, nullable=True)
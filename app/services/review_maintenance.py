"""One bounded, provider-free maintenance pass for human review deadlines."""

from app.db.session import SessionLocal
from app.services.escalation import expire_overdue_reviews


def maintain_reviews(limit=100, session_factory=None):
    factory = session_factory or SessionLocal
    with factory() as db:
        return {'expired': len(expire_overdue_reviews(db, limit=limit))}

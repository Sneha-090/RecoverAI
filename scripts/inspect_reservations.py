"""Read-only view of active and interrupted work; never retries provider calls.

Run: python -m scripts.inspect_reservations
"""

import json

from app.db.session import SessionLocal
from app.models.models import RecoveryReservation, WebhookReceipt


def inspect_reservations(db):
    return {
        "recovery": [
            {"payment_id": row.payment_id, "state": row.state, "updated_at": row.updated_at.isoformat()}
            for row in db.query(RecoveryReservation).order_by(RecoveryReservation.updated_at).all()
        ],
        "webhooks": [
            {"event_id": row.event_id, "state": row.state, "created_at": row.created_at.isoformat()}
            for row in db.query(WebhookReceipt).filter(WebhookReceipt.state != "processed")
            .order_by(WebhookReceipt.created_at).all()
        ],
    }


if __name__ == "__main__":
    with SessionLocal() as db:
        print(json.dumps(inspect_reservations(db), indent=2))

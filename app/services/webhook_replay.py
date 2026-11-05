"""Bounded replay of verified inbox events, using the normal durable claims."""

import json
from datetime import datetime

from app.db.session import SessionLocal
from app.models.models import WebhookInbox
from app.services.webhook_inbox import REPLAYABLE_STATES


def replay_batch(limit=100, event_id=None, session_factory=None):
    if not 1 <= limit <= 1000:
        raise ValueError("Replay limit must be between 1 and 1000")
    factory = session_factory or SessionLocal
    with factory() as db:
        query = db.query(WebhookInbox.event_id).filter(WebhookInbox.state.in_(REPLAYABLE_STATES))
        if event_id:
            query = query.filter(WebhookInbox.event_id == event_id)
        else:
            query = query.filter(WebhookInbox.available_at <= datetime.utcnow())
        ids = [row[0] for row in query.order_by(WebhookInbox.available_at, WebhookInbox.event_id).limit(limit).all()]
    summary = {"selected": len(ids), "processed": 0, "waiting": 0, "blocked": 0, "errors": 0}
    # Import here to avoid coupling the intake service to a worker at startup.
    from app.api.webhooks import process_verified_webhook
    for selected_id in ids:
        with factory() as db:
            row = db.get(WebhookInbox, selected_id)
            if row is None or row.state not in REPLAYABLE_STATES:
                continue
            try:
                process_verified_webhook(db, json.loads(row.payload_json), selected_id)
            except Exception:
                # The processor keeps interrupted/ambiguous side effects blocked.
                # Do not log provider exceptions, payloads, contacts or secrets.
                summary["errors"] += 1
                db.rollback()
            db.expire_all()
            row = db.get(WebhookInbox, selected_id)
            state = row.state if row else "needs_reconciliation"
            key = "processed" if state == "processed" else "waiting" if state in REPLAYABLE_STATES else "blocked"
            summary[key] += 1
    return summary

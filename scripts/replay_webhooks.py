"""Replay only verified pending events. Never force processing/reconciliation claims."""

import argparse
import json
import time

from app.db.session import SessionLocal
from app.models.models import WebhookInbox
from app.services.webhook_replay import replay_batch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--event-id", help="Retry this waiting event now, without bypassing claims")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="Poll due events until stopped")
    mode.add_argument("--list", action="store_true", help="Show IDs and states only; do not process events")
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000 or not 1 <= args.interval <= 3600:
        parser.error("limit must be 1..1000 and interval must be 1..3600 seconds")
    if args.watch and args.event_id:
        parser.error("Use --event-id for a single controlled retry, without --watch")
    if args.list:
        with SessionLocal() as db:
            query = db.query(WebhookInbox)
            if args.event_id:
                query = query.filter_by(event_id=args.event_id)
            rows = query.order_by(WebhookInbox.created_at.desc(), WebhookInbox.event_id).limit(args.limit).all()
            print(json.dumps([{"event_id": row.event_id, "state": row.state,
                               "attempts": row.attempts} for row in rows]))
        return
    try:
        while True:
            summary = replay_batch(limit=args.limit, event_id=args.event_id)
            if summary["selected"] or not args.watch:
                print(json.dumps(summary), flush=True)
            if not args.watch:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()

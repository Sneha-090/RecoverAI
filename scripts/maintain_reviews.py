"""Expire overdue reviews locally; never create or retry provider resources."""

import argparse
import json
import time

from app.services.review_maintenance import maintain_reviews


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true', help='Keep checking deadlines until stopped')
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000 or not 1 <= args.interval <= 3600:
        parser.error('limit must be 1..1000 and interval must be 1..3600 seconds')
    try:
        while True:
            try:
                result = maintain_reviews(limit=args.limit)
                if result['expired'] or not args.watch:
                    print(json.dumps(result), flush=True)
            except Exception:
                if not args.watch:
                    raise SystemExit('Review maintenance could not complete. No payment action was requested.') from None
                print(json.dumps({'error': 'Review maintenance could not complete; retrying after the interval.'}), flush=True)
            if not args.watch:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return


if __name__ == '__main__':
    main()

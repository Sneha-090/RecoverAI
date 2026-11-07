"""Follow up due Test Mode recovery cases using normal outcome verification."""

import argparse
import json
import time

from app.services.outcome_polling import poll_pending_outcomes


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--limit',type=int,default=25)
    parser.add_argument('--interval',type=int,default=60)
    parser.add_argument('--min-age',type=int,default=60)
    args=parser.parse_args(argv)
    if not 1<=args.limit<=100 or not 10<=args.interval<=3600 or not 10<=args.min_age<=86400:
        parser.error('limit must be 1..100, interval 10..3600, min-age 10..86400 seconds')
    try:
        while True:
            summary=poll_pending_outcomes(args.limit,args.min_age)
            if summary['selected'] or not args.watch:print(json.dumps(summary),flush=True)
            if not args.watch:return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return


if __name__=='__main__':main()

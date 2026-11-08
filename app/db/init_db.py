"""Apply reviewed migrations; explicitly adopt a matching legacy database once."""

import argparse
import json

from app.db.session import engine
from app.db.schema import migrate_database,schema_status,SchemaStateError


def init_db(adopt_legacy=False,backup_directory=None):
    return migrate_database(engine,adopt_legacy=adopt_legacy,backup_directory=backup_directory)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adopt-legacy',action='store_true')
    parser.add_argument('--status',action='store_true')
    args=parser.parse_args(argv)
    try:
        result=schema_status(engine) if args.status else init_db(args.adopt_legacy)
    except SchemaStateError as error:raise SystemExit(str(error)) from None
    except Exception:raise SystemExit('Database migration failed. Keep services stopped and review the local backup and migration state.') from None
    print(json.dumps(result))


if __name__=='__main__':main()

# Reviewed schema upgrades

Run commands from the project root with the configured environment. Stop all app
and worker processes before maintenance. Fresh databases use:

```
python -m app.db.init_db
python -m app.db.init_db --status
```

A one-time existing unversioned SQLite database adoption must be explicit:

```
python -m app.db.init_db --adopt-legacy
```

The helper compares every table/column, key, index and foreign key against the
frozen baseline manifest, checks reference integrity, makes a consistent SQLite
backup under `var/backups` and verifies its integrity before stamping/upgrading.
Unknown/different schemas and unknown revisions stop without a guessed stamp.
The baseline migration is frozen SQLAlchemy operations, not mutable model
`create_all`. A migration ownership file prevents competing migrators and is
not automatically expired. Investigate stale locks before manual removal.

Backups, credentials and local operation state are gitignored. Keep a backup on
another protected volume for a real pilot; a same-drive backup is recovery aid,
not protection against drive loss. Baseline downgrades refuse to delete data.
SQLite schema changes can have nontransactional DDL: on migration failure, keep
services stopped and review/restore the verified backup before proceeding.
Versioned PostgreSQL deployments need their own reviewed backup procedure;
automatic legacy adoption here is limited to SQLite.

For a future schema change, add a reviewed Alembic revision, test a fresh upgrade
and an upgrade retaining existing records, and run `alembic check` after upgrade.
Do not stamp a differing database to bypass a migration. Internal `/ready` checks
schema version, configured operator access and model artifact integrity; `/health`
is process liveness. The public webhook-only gateway exposes neither readiness
nor operator routes. Readiness does not contact Razorpay or prove its credentials
or merchant configuration are valid.

Revision 0002 adds permanent original-order recovery ownership. Existing work on
one payment keeps its ownership even when another attempt is older. Multiple
already-acted cases for the same order become ambiguous and block new collection;
no action, execution or outcome is merged/deleted. Fresh competing failed attempts
share one owner. Ownership is never reassigned merely because that case closes.
An invoice spanning distinct provider orders still needs merchant-approved mapping.

Revision 0003 adds nullable persistent operator-stop reason/timestamp columns to
payments, retaining existing cases. Stops survive app/worker restarts. Downgrades
refuse to discard stop history. Use reviewed backups rather than deleting flags.

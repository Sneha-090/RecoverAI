"""Database URL stays in local settings, never in migration configuration files."""

from alembic import context
from app.config import settings
from app.db.session import Base,engine
from app.models import models  # noqa: F401

config=context.config


def run(connection):
    context.configure(connection=connection,target_metadata=Base.metadata,
                      compare_type=True,render_as_batch=connection.dialect.name=='sqlite')
    with context.begin_transaction():context.run_migrations()


if context.is_offline_mode():
    context.configure(url=settings.database_url,target_metadata=Base.metadata,
                      literal_binds=True,compare_type=True)
    with context.begin_transaction():context.run_migrations()
elif config.attributes.get('connection') is not None:
    run(config.attributes['connection'])
else:
    with engine.connect() as connection:run(connection)

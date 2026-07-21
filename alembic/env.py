import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ----------------------------------------------------------------------
# 1. Add project root to sys.path to allow importing from news_collector
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from news_collector.config import DATABASE_CONFIG
from news_collector.storage.database import build_database_url
from news_collector.storage.models import Base

# ----------------------------------------------------------------------
# 2. Config Setup
# ----------------------------------------------------------------------

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ----------------------------------------------------------------------
# 3. Model Metadata and DB URL
# ----------------------------------------------------------------------
target_metadata = Base.metadata

# Construct SQLAlchemy URL from app config via the same build_database_url()
# DatabaseManager and the read-only migration guard use — this used to be a
# third, independent copy of this logic, and it had drifted: its postgresql
# branch interpolated user/password into an f-string with no percent-encoding,
# unlike URL.create() (a password containing "@", ":", "/", or "%" would have
# produced a silently wrong or unparsable URL). One builder, one behavior.
db_config = dict(DATABASE_CONFIG)
if db_config.get("type") == "sqlite" and db_config.get("path"):
    # Alembic can run standalone (CLI), outside get_runtime_config()'s own
    # path resolution, so a relative sqlite path is resolved here against the
    # project root — build_database_url() itself does no path resolution.
    db_path = Path(db_config["path"])
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_config["path"] = db_path

db_url = ""
if db_config.get("type") in ("sqlite", "postgresql"):
    url = build_database_url(db_config)
    db_url = (
        url.render_as_string(hide_password=False)
        if hasattr(url, "render_as_string")
        else str(url)
    )

# Override the url in alembic config object so migrations run against correct DB
config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=bool(
            config.get_main_option("sqlalchemy.url", "").startswith("sqlite")
        ),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=bool(
                config.get_main_option("sqlalchemy.url", "").startswith("sqlite")
            ),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

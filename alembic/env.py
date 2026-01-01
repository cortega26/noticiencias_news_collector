import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ----------------------------------------------------------------------
# 1. Add project root to sys.path to allow importing from news_collector
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from news_collector.config import DATABASE_CONFIG
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

# Construct SQLAlchemy URL from app config
db_url = ""
if DATABASE_CONFIG.get("type") == "sqlite":
    db_path = DATABASE_CONFIG.get("path")
    if db_path:
        # If path is relative, make it absolute relative to project root
        if not Path(db_path).is_absolute():
            db_path = BASE_DIR / db_path
        db_url = f"sqlite:///{db_path}"
elif DATABASE_CONFIG.get("type") == "postgresql":
    # Construct PG URL
    user = DATABASE_CONFIG.get("user")
    pw = DATABASE_CONFIG.get("password")
    host = DATABASE_CONFIG.get("host")
    port = DATABASE_CONFIG.get("port")
    db = DATABASE_CONFIG.get("database")
    db_url = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

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
        render_as_batch=True if config.get_main_option("sqlalchemy.url", "").startswith("sqlite") else False,
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
            render_as_batch=True if config.get_main_option("sqlalchemy.url", "").startswith("sqlite") else False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

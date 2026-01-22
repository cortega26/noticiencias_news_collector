#!/usr/bin/env python3
"""
Database Migration Helper Script
================================

Wrapper around alembic to simplify manual database migration tasks.
Usage:
    python scripts/migrate.py make "Message"  # Create a new migration
    python scripts/migrate.py up              # Upgrade to latest version
    python scripts/migrate.py down            # Downgrade one step
    python scripts/migrate.py history         # Show migration history
"""

import os
import subprocess
import sys
from typing import List

import click

# Ensure project root is in path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from news_collector.config import DATABASE_CONFIG


@click.group()
def cli():
    """Database migration management."""
    pass


@cli.command()
@click.argument("message")
def make(message: str):
    """Create a new migration with the given message."""
    print(f"Creating migration: {message}")
    run_alembic(["revision", "--autogenerate", "-m", message])


@cli.command()
def up():
    """Upgrade database to the latest version."""
    print("Upgrading database schema...")
    run_alembic(["upgrade", "head"])


@cli.command()
def down():
    """Downgrade database one revision."""
    print("Downgrading database schema...")
    run_alembic(["downgrade", "-1"])


@cli.command()
def history():
    """Show migration history."""
    run_alembic(["history", "--verbose"])


def run_alembic(args: List[str]):
    """Run alembic command with proper environment."""
    cmd = ["python", "-m", "alembic"] + args

    # Note: runtime schema bootstrapping uses DatabaseManager.create_all +
    # _run_schema_migrations. Alembic is only for manual/production workflows.
    # We don't need to pass DB url here because env.py reads it from app config.
    try:
        subprocess.run(cmd, cwd=BASE_DIR, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running alembic: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()

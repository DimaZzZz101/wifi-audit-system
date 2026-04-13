"""Safe Alembic bootstrap for container startup.

If legacy tables exist but alembic_version is missing (old create_all flow),
stamp current schema as head once, then run regular upgrades.

After migrations, removes orphaned project directories (dirs in ARTIFACTS_DIR/projects/
that have no corresponding record in the project table). This happens when the DB is
recreated (e.g. docker compose down -v) but the artifacts bind mount persists.
"""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def _cleanup_orphaned_projects(database_url: str, artifacts_dir: str) -> None:
    """Remove project dirs that have no record in the project table (e.g. after DB reset)."""
    projects_base = Path(artifacts_dir) / "projects"
    if not projects_base.exists() or not projects_base.is_dir():
        sessions_base = Path(artifacts_dir) / "sessions"
        if sessions_base.exists() and sessions_base.is_dir():
            projects_base = sessions_base
        else:
            return

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT slug FROM project"))
            valid_slugs = {row[0] for row in result.fetchall()}
    except Exception as e:
        print(f"Skip orphaned projects cleanup (project table may not exist): {e}")
        return
    finally:
        await engine.dispose()

    for item in projects_base.iterdir():
        if item.is_dir() and item.name not in valid_slugs:
            try:
                shutil.rmtree(item)
                print(f"Removed orphaned project dir: {item.name}")
            except OSError as e:
                print(f"Warning: could not remove {item}: {e}")


async def _table_exists(database_url: str, table_name: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                    )
                    """
                ),
                {"table_name": table_name},
            )
            return bool(result.scalar())
    finally:
        await engine.dispose()


def _run_alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


async def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    users_exists = await _table_exists(database_url, "users")
    alembic_exists = await _table_exists(database_url, "alembic_version")

    if users_exists and not alembic_exists:
        print("Legacy schema detected (users exists, alembic_version missing). Stamping head...")
        _run_alembic("stamp", "head")

    print("Running alembic upgrade head...")
    _run_alembic("upgrade", "head")

    artifacts_dir = os.getenv("ARTIFACTS_DIR", "/data/artifacts").strip()
    if artifacts_dir:
        await _cleanup_orphaned_projects(database_url, artifacts_dir)


if __name__ == "__main__":
    asyncio.run(main())

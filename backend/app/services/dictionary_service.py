"""Dictionary service: CRUD for system-level wordlists."""
from __future__ import annotations

import asyncio
import io
import itertools
import logging
import string
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_maker
from app.models.dictionary import Dictionary

log = logging.getLogger(__name__)

_generating_tasks: dict[int, asyncio.Task] = {}

MASK_CHARSETS: dict[str, str] = {
    "d": string.digits,
    "l": string.ascii_lowercase,
    "u": string.ascii_uppercase,
    "s": " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
    "a": string.ascii_letters + string.digits + " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
    "h": "0123456789abcdef",
    "H": "0123456789ABCDEF",
}


def _dict_dir() -> Path:
    settings = get_settings()
    d = Path(settings.artifacts_dir) / "dictionaries"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def list_dictionaries() -> list[dict[str, Any]]:
    async with async_session_maker() as db:
        rows = await db.execute(
            select(Dictionary).order_by(Dictionary.created_at.desc())
        )
        dicts = rows.scalars().all()
        return [_to_dict(d) for d in dicts]


async def get_dictionary(dict_id: int) -> dict[str, Any] | None:
    async with async_session_maker() as db:
        row = await db.execute(select(Dictionary).where(Dictionary.id == dict_id))
        d = row.scalar_one_or_none()
        return _to_dict(d) if d else None


async def create_dictionary(name: str, filename: str, content: bytes, description: str | None = None) -> dict[str, Any]:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = _dict_dir() / safe_name

    counter = 0
    while dest.exists():
        counter += 1
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        dest = _dict_dir() / f"{stem}_{counter}{suffix}"

    dest.write_bytes(content)
    size = dest.stat().st_size
    word_count = content.count(b"\n")

    async with async_session_maker() as db:
        d = Dictionary(
            name=name,
            description=description,
            filename=dest.name,
            size_bytes=size,
            word_count=word_count,
        )
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return _to_dict(d)


async def delete_dictionary(dict_id: int) -> bool:
    async with async_session_maker() as db:
        row = await db.execute(select(Dictionary).where(Dictionary.id == dict_id))
        d = row.scalar_one_or_none()
        if not d:
            return False
        task = _generating_tasks.pop(d.id, None)
        if task and not task.done():
            task.cancel()
        fpath = _dict_dir() / d.filename
        if fpath.exists():
            fpath.unlink(missing_ok=True)
        await db.delete(d)
        await db.commit()
        return True


async def generate_dictionary(name: str, masks: list[str], description: str | None = None) -> dict[str, Any]:
    safe = name.replace("/", "_").replace(" ", "_")
    dest = _dict_dir() / f"{safe}.txt"
    counter = 0
    while dest.exists():
        counter += 1
        dest = _dict_dir() / f"{safe}_{counter}.txt"

    dest.write_text("")

    async with async_session_maker() as db:
        d = Dictionary(
            name=name,
            description=description or f"Generating from: {', '.join(masks)}",
            filename=dest.name,
            size_bytes=0,
            word_count=0,
        )
        db.add(d)
        await db.commit()
        await db.refresh(d)
        dict_id = d.id
        result = _to_dict(d)

    task = asyncio.create_task(_background_generate(dict_id, dest, masks))
    _generating_tasks[dict_id] = task

    return result


async def cleanup_orphan_files() -> int:
    """Remove dictionary files on disk that have no matching DB record."""
    d = _dict_dir()
    if not d.exists():
        return 0

    async with async_session_maker() as db:
        rows = await db.execute(select(Dictionary.filename))
        known_filenames = {r[0] for r in rows.all()}

    removed = 0
    for f in d.iterdir():
        if f.is_file() and f.name not in known_filenames:
            log.info("Removing orphan dictionary file: %s", f.name)
            f.unlink(missing_ok=True)
            removed += 1
    return removed


async def _background_generate(dict_id: int, dest: Path, masks: list[str]) -> None:
    try:
        size, word_count = await asyncio.to_thread(_do_generate, dest, masks)

        async with async_session_maker() as db:
            await db.execute(
                update(Dictionary)
                .where(Dictionary.id == dict_id)
                .values(
                    size_bytes=size,
                    word_count=word_count,
                    description=f"Generated from: {', '.join(masks)} ({word_count:,} words)",
                )
            )
            await db.commit()
        log.info("Dictionary %d generated: %d words, %d bytes", dict_id, word_count, size)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Dictionary %d generation failed", dict_id)
        async with async_session_maker() as db:
            await db.execute(
                update(Dictionary)
                .where(Dictionary.id == dict_id)
                .values(description="Generation failed")
            )
            await db.commit()
    finally:
        _generating_tasks.pop(dict_id, None)


def _do_generate(dest: Path, masks: list[str]) -> tuple[int, int]:
    word_count = 0
    with open(dest, "w", encoding="utf-8", buffering=1024 * 1024) as f:
        for mask in masks:
            mask_count = 0
            try:
                proc = subprocess.Popen(
                    ["john", f"--mask={mask}", "--stdout"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1024 * 1024,
                )
                for line in proc.stdout:
                    f.write(line)
                    word_count += 1
                    mask_count += 1
                proc.wait(timeout=30)
                if proc.returncode != 0 and mask_count == 0:
                    log.warning("john mask generation failed for %s (code=%s), using Python fallback", mask, proc.returncode)
                    word_count += _generate_mask_python(mask, f)
            except (FileNotFoundError, OSError):
                log.warning("john executable is unavailable, using Python fallback")
                word_count += _generate_mask_python(mask, f)
            except subprocess.TimeoutExpired:
                proc.kill()
                log.warning("john timed out for mask %s, using Python fallback", mask)
                word_count += _generate_mask_python(mask, f)

    size = dest.stat().st_size
    return size, word_count


def get_dictionary_path(filename: str) -> Path | None:
    p = _dict_dir() / filename
    return p if p.exists() else None


def _parse_mask(mask: str) -> list[str] | None:
    """Parse a john/hashcat-style mask into a list of charset strings per position.
    Returns None if the mask is invalid or empty."""
    charsets: list[str] = []
    i = 0
    while i < len(mask):
        if mask[i] == "?" and i + 1 < len(mask):
            key = mask[i + 1]
            cs = MASK_CHARSETS.get(key)
            if cs is None:
                return None
            charsets.append(cs)
            i += 2
        else:
            charsets.append(mask[i])
            i += 1
    return charsets if charsets else None


def _generate_mask_python(mask: str, f: io.TextIOBase) -> int:
    """Python fallback that supports all mask charsets (?d ?l ?u ?s ?a ?h ?H)."""
    charsets = _parse_mask(mask)
    if charsets is None:
        return 0

    total_combos = 1
    for cs in charsets:
        total_combos *= len(cs)
    if total_combos > 500_000_000:
        log.warning("Mask %s has %d combinations, capping at 500M", mask, total_combos)
        return 0

    buf: list[str] = []
    count = 0
    flush_every = 100_000

    for combo in itertools.product(*charsets):
        buf.append("".join(combo))
        buf.append("\n")
        count += 1
        if count % flush_every == 0:
            f.write("".join(buf))
            buf.clear()
    if buf:
        f.write("".join(buf))
    return count


async def shutdown() -> None:
    for task in list(_generating_tasks.values()):
        if not task.done():
            task.cancel()
    for task in list(_generating_tasks.values()):
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _generating_tasks.clear()


def _to_dict(d: Dictionary) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "filename": d.filename,
        "size_bytes": d.size_bytes,
        "word_count": d.word_count,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }

"""Сервис проектов аудита: создание директорий, пути к артефактам."""
import shutil
from pathlib import Path

from app.config import get_settings

def get_projects_base_dir() -> Path:
    """Базовый каталог для проектов: ARTIFACTS_DIR/projects."""
    settings = get_settings()
    base = Path(settings.artifacts_dir) / "projects"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _migrate_legacy_dir(slug: str) -> None:
    """Move project dir from legacy sessions/ to projects/ if needed."""
    settings = get_settings()
    legacy = Path(settings.artifacts_dir) / "sessions" / slug
    target = Path(settings.artifacts_dir) / "projects" / slug
    if not legacy.exists() or not legacy.is_dir():
        return
    if not target.exists():
        try:
            shutil.move(str(legacy), str(target))
        except OSError:
            pass
    else:
        for item in legacy.iterdir():
            dest = target / item.name
            if not dest.exists():
                try:
                    shutil.move(str(item), str(dest))
                except OSError:
                    pass
        try:
            shutil.rmtree(legacy, ignore_errors=True)
        except OSError:
            pass


def get_project_dir(slug: str) -> Path:
    """Путь к директории проекта по slug."""
    _migrate_legacy_dir(slug)
    return get_projects_base_dir() / slug


def ensure_project_dirs(slug: str) -> Path:
    """Создаёт только корневую директорию проекта. Возвращает путь к корню проекта."""
    _migrate_legacy_dir(slug)
    base = get_projects_base_dir() / slug
    base.mkdir(parents=True, exist_ok=True)
    return base


def remove_project_dir(slug: str) -> None:
    """Удалить директорию проекта и всё её содержимое."""
    base = get_project_dir(slug)
    if base.exists() and base.is_dir():
        try:
            shutil.rmtree(base)
        except OSError:
            pass


def write_mac_filter_file(slug: str, entries: list[str]) -> Path:
    """Write mac_filter.txt (one MAC per line) into the project directory."""
    base = get_project_dir(slug)
    base.mkdir(parents=True, exist_ok=True)
    fpath = base / "mac_filter.txt"
    fpath.write_text("\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
    return fpath


def resolve_project_path(slug: str, subpath: str = "") -> Path | None:
    """
    Разрешает путь внутри директории проекта. Защита от path traversal.
    Возвращает Path или None если путь выходит за пределы проекта.
    """
    base = get_project_dir(slug)
    if not base.exists():
        return None
    if not subpath or subpath == ".":
        return base
    try:
        resolved = (base / subpath).resolve()
        base_resolved = base.resolve()
        resolved.relative_to(base_resolved)
        return resolved
    except (OSError, ValueError, TypeError):
        return None

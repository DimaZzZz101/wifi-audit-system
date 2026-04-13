"""Скачивание и установка модулей из удалённого каталога."""
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.config import get_settings
from app.plugins.registry import SYSTEM_PLUGINS
from app.plugins.manifest import normalize_manifest
from app.plugins.loader import load_plugins_from_dir

# Имя флага после скачивания (путь к файлу пакета)
DOWNLOAD_FLAG = ".module_downloaded"
MAX_MODULE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
MODULE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _plugins_dir() -> str:
    d = get_settings().plugins_dir or ""
    return d.strip()


def _temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / "wifiaudit_modules"


def _is_valid_module_id(module_id: str) -> bool:
    return bool(module_id and MODULE_ID_RE.fullmatch(module_id))


def _safe_child_path(root: Path, child_name: str) -> Path:
    target = (root / child_name).resolve()
    root_resolved = root.resolve()
    if os.path.commonpath([target, root_resolved]) != str(root_resolved):
        raise ValueError("Path escapes plugins directory")
    return target


def _is_safe_tar_member_name(name: str) -> bool:
    member_path = PurePosixPath(name)
    if member_path.is_absolute():
        return False
    if any(part in ("", ".", "..") for part in member_path.parts):
        return False
    return True


def _safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    destination_resolved = destination.resolve()
    for member in tar.getmembers():
        if not _is_safe_tar_member_name(member.name):
            raise ValueError("Archive contains unsafe path")
        if member.issym() or member.islnk():
            raise ValueError("Archive contains symbolic or hard links")
        if not (member.isfile() or member.isdir()):
            raise ValueError("Archive contains unsupported entry type")
        target = (destination / member.name).resolve()
        if os.path.commonpath([target, destination_resolved]) != str(destination_resolved):
            raise ValueError("Archive entry escapes extraction directory")
    tar.extractall(destination)


def get_installed_modules() -> list[dict[str, Any]]:
    """Список установленных модулей: из каталога + системные (с полем system=True/False)."""
    plugins_dir = _plugins_dir()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Из каталога (только те, что реально на диске - не системные)
    for p in load_plugins_from_dir(plugins_dir):
        pid = p.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            out = dict(p)
            out["system"] = False
            out["removable"] = True
            result.append(out)

    # Системные (встроенные)
    for pid, p in SYSTEM_PLUGINS.items():
        if pid not in seen:
            seen.add(pid)
            out = {
                "id": p["id"],
                "name": p["name"],
                "type": p["type"],
                "description": p.get("description"),
                "version": p.get("version"),
                "author": p.get("author"),
                "provides": p.get("provides") or [],
                "container": p.get("container"),
                "frontend": p.get("frontend"),
            }
            out["system"] = True
            out["removable"] = False
            result.append(out)

    return result


async def fetch_available_modules() -> list[dict[str, Any]]:
    """Список модулей, доступных для установки (из MODULES_INDEX_URL)."""
    url = (get_settings().modules_index_url or "").strip()
    if not url:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    result: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            result.append({
                "id": str(item.get("id", "")),
                "name": str(item.get("name", item["id"])),
                "version": str(item.get("version", "")),
                "description": item.get("description"),
                "author": item.get("author"),
                "download_url": item.get("download_url"),
                "checksum": item.get("checksum"),  # sha256
            })
    return result


async def download_module(download_url: str) -> tuple[str | None, str | None]:
    """
    Скачать пакет по URL во временный файл.
    Возвращает (path_to_tar_gz, error_message).
    """
    base_url = (get_settings().modules_download_base_url or "").strip()
    url = download_url if download_url.startswith("http") else (base_url.rstrip("/") + "/" + download_url.lstrip("/"))
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None, "Invalid download URL"

    _temp_dir().mkdir(parents=True, exist_ok=True)
    # Не используем имя из URL напрямую, чтобы избежать коллизий и подмен.
    filename = f"module-{uuid4().hex}.tar.gz"
    dest = _temp_dir() / filename

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(url, follow_redirects=True)
            r.raise_for_status()
            content_length = r.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_MODULE_SIZE_BYTES:
                        return None, f"Package too large (max {MAX_MODULE_SIZE_BYTES} bytes)"
                except ValueError:
                    pass
            with open(dest, "wb") as f:
                downloaded = 0
                async for chunk in r.aiter_bytes():
                    downloaded += len(chunk)
                    if downloaded > MAX_MODULE_SIZE_BYTES:
                        raise ValueError(f"Package too large (max {MAX_MODULE_SIZE_BYTES} bytes)")
                    f.write(chunk)
        flag = _temp_dir() / DOWNLOAD_FLAG
        flag.write_text(dest.as_posix())
        return dest.as_posix(), None
    except Exception as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return None, str(e)


def get_download_status() -> dict[str, Any]:
    """Проверить, есть ли скачанный пакет (для асинхронной установки)."""
    flag = _temp_dir() / DOWNLOAD_FLAG
    if not flag.exists():
        return {"success": False, "path": None}
    path = flag.read_text().strip()
    return {"success": Path(path).exists(), "path": path if Path(path).exists() else None}


def _extract_and_install(tar_path: str, plugins_dir: str) -> tuple[str | None, str | None]:
    """
    Распаковать tar.gz в PLUGINS_DIR.
    Ожидается: один верхний каталог (имя = id модуля), внутри manifest.json или <id>.plugin.json.
    Возвращает (module_id, error).
    """
    root = Path(plugins_dir)
    root.mkdir(parents=True, exist_ok=True)
    tf = Path(tar_path)
    if not tf.exists():
        return None, "Downloaded file not found"

    try:
        with tarfile.open(tf, "r:gz") as tar:
            names = tar.getnames()
            if not names:
                return None, "Archive is empty"
            # Безопасность: все пути должны быть внутри одной верхней папки
            top = names[0].split("/")[0]
            if not _is_valid_module_id(top):
                return None, "Invalid archive top directory name"
            for n in names:
                if not n.startswith(top + "/") and n != top:
                    return None, "Invalid archive structure"
            # Ищем manifest в архиве
            manifest_in_archive = None
            for n in names:
                if n.endswith("manifest.json") or n.endswith(".plugin.json"):
                    manifest_in_archive = n
                    break
            if not manifest_in_archive:
                return None, "No manifest.json or *.plugin.json in archive"
            module_id = top
            # Извлекаем во временную папку, затем копируем в plugins_dir
            tmp = Path(tempfile.mkdtemp(prefix="wifiaudit_install_"))
            try:
                _safe_extract_tar(tar, tmp)
                src_dir = tmp / top
                if not src_dir.is_dir():
                    return None, "Invalid archive: missing top directory"
                # Читаем манифест, чтобы получить id (папка в PLUGINS_DIR = id из манифеста)
                manifest_path = None
                for candidate in [src_dir / "manifest.json", src_dir / f"{top}.plugin.json"]:
                    if candidate.exists():
                        manifest_path = candidate
                        break
                if manifest_path is None or not manifest_path.exists():
                    return None, "Manifest not found in archive"
                with open(manifest_path, encoding="utf-8") as f:
                    data = json.load(f)
                normalized = normalize_manifest(data)
                module_id = normalized.get("id") or top
                if not _is_valid_module_id(module_id):
                    return None, "Invalid module id in manifest"
                dest_dir = _safe_child_path(root, module_id)
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                shutil.copytree(src_dir, dest_dir)
                return module_id, None
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        return None, str(e)


def install_downloaded_module(checksum: str | None = None) -> tuple[str | None, str | None]:
    """
    Установить ранее скачанный пакет. Проверяет checksum (sha256), если передан.
    Возвращает (module_id, error).
    """
    status = get_download_status()
    if not status.get("success") or not status.get("path"):
        return None, "No downloaded package. Download first."
    path = status["path"]
    plugins_dir = _plugins_dir()
    if not plugins_dir:
        return None, "PLUGINS_DIR is not configured"

    if checksum:
        with open(path, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        if h.lower() != checksum.lower():
            return None, "Checksum mismatch"

    module_id, err = _extract_and_install(path, plugins_dir)
    if err:
        return None, err
    # Очистить флаг скачивания и временный файл
    (Path(path).parent / DOWNLOAD_FLAG).unlink(missing_ok=True)
    Path(path).unlink(missing_ok=True)
    return module_id, None


def remove_module(module_id: str) -> tuple[bool, str | None]:
    """
    Удалить установленный модуль (только не системный).
    Возвращает (success, error).
    """
    if module_id in SYSTEM_PLUGINS:
        return False, "Cannot remove system module"
    if not _is_valid_module_id(module_id):
        return False, "Invalid module id"
    plugins_dir = _plugins_dir()
    if not plugins_dir:
        return False, "PLUGINS_DIR is not configured"
    root = Path(plugins_dir)
    # Удалить каталог или один файл .plugin.json
    dir_path = _safe_child_path(root, module_id)
    file_path = _safe_child_path(root, f"{module_id}.plugin.json")
    if dir_path.is_dir():
        shutil.rmtree(dir_path)
        return True, None
    if file_path.is_file():
        file_path.unlink()
        return True, None
    return False, "Module not found or not installed"

"""Сервис реестра образов WiFi Audit - образы инструментов (только для чтения)."""
from __future__ import annotations

from app.services import session_tools


def get_registry_allow_list_from_tools() -> list[str]:
    """Список образов из определений инструментов. Реестр только для чтения."""
    return [t["image"] for t in session_tools.AVAILABLE_TOOLS.values()]


def get_registry_entries_from_tools() -> list[dict]:
    """Записи реестра: image, tool_id, tool_name для каждого инструмента."""
    return [
        {
            "image_reference": t["image"],
            "tool_id": t["id"],
            "tool_name": t["name"],
        }
        for t in session_tools.AVAILABLE_TOOLS.values()
    ]


def _normalize_tag(tag: str) -> str:
    """Приводим тег к виду без registry prefix для сравнения (docker.io/library/busybox:latest -> busybox:latest)."""
    if not tag or tag == "<none>:<none>":
        return ""
    # Убираем известные префиксы реестра
    for prefix in ("docker.io/library/", "docker.io/", "library/"):
        if tag.startswith(prefix):
            tag = tag[len(prefix):]
            break
    return tag.strip().lower()


def get_matching_registry_reference(image_tags: list[str], allow_list: list[str]) -> str | None:
    """Возвращает первую ссылку из allow_list, совпадающую с одним из тегов образа (для DELETE)."""
    if not image_tags or not allow_list:
        return None
    allow_set = {_normalize_tag(r): r for r in allow_list}
    for t in image_tags:
        norm = _normalize_tag(t)
        if norm in allow_set:
            return allow_set[norm]
        if t in allow_list:
            return t
    return None


def image_matches_registry(image_tags: list[str], allow_list: list[str]) -> bool:
    """
    Проверяет, входит ли образ (по списку его тегов) в реестр.
    Сравнение: точное совпадение или совпадение после нормализации (без docker.io/library/).
    """
    if not image_tags or not allow_list:
        return False
    allow_set = {_normalize_tag(r) for r in allow_list}
    for t in image_tags:
        if _normalize_tag(t) in allow_set:
            return True
        if t in allow_list:
            return True
    return False


def is_image_reference_in_registry(image_reference: str, allow_list: list[str]) -> bool:
    """Проверяет, входит ли одна ссылка на образ (name:tag) в реестр."""
    if not image_reference or not allow_list:
        return False
    ref = image_reference.strip()
    norm = _normalize_tag(ref)
    allow_set = {_normalize_tag(r) for r in allow_list}
    return norm in allow_set or ref in allow_list

"""Unit tests: app.plugins.manifest"""
import pytest

from app.plugins.manifest import normalize_manifest


def test_normalize_valid_minimal():
    """
    Минимальный валидный манифест.
    Вход: dict с id, name, type.
    Выход: container и frontend равны None; provides - [].
    """
    out = normalize_manifest({"id": "x", "name": "X", "type": "tool"})
    assert out["container"] is None
    assert out["frontend"] is None
    assert out["provides"] == []


def test_normalize_missing_id_raises():
    """
    Без поля id - ValueError.
    Вход: dict без id.
    Выход: ValueError.
    """
    with pytest.raises(ValueError):
        normalize_manifest({"name": "X", "type": "t"})


def test_normalize_missing_name_raises():
    """
    Без поля name - ValueError.
    Вход: dict с id, но без name.
    Выход: ValueError.
    """
    with pytest.raises(ValueError):
        normalize_manifest({"id": "x", "type": "t"})


def test_normalize_empty_id_raises():
    """
    Пустая строка id - ValueError.
    Вход: dict с id="", name="X", type="t".
    Выход: ValueError.
    """
    with pytest.raises(ValueError):
        normalize_manifest({"id": "", "name": "X", "type": "t"})


def test_normalize_with_container():
    """
    Манифест с секцией container.
    Вход: dict с id="p", name="P", type="tool", container={"image": "img:1", "type": "instrumental"}.   
    Выход: нормализованные вложенные поля.
    """
    out = normalize_manifest(
        {
            "id": "p",
            "name": "P",
            "type": "tool",
            "container": {"image": "img:1", "type": "instrumental"},
        }
    )
    assert out["container"]["image"] == "img:1"
    assert out["container"]["type"] == "instrumental"


def test_normalize_with_frontend():
    """
    Манифест с frontend.bundle_url.
    Вход: dict с id="p", name="P", type="tool", frontend={"bundle_url": "http://example.com/b.js"}.
    Выход: URL совпадает.
    """
    out = normalize_manifest(
        {
            "id": "p",
            "name": "P",
            "type": "tool",
            "frontend": {"bundle_url": "http://example.com/b.js"},
        }
    )
    assert out["frontend"]["bundle_url"] == "http://example.com/b.js"


def test_normalize_provides_list():
    """
    provides - список строк.
    Вход: dict с id="p", name="P", type="tool", provides=["status_tiles"].
    Выход: тот же список.
    """
    out = normalize_manifest(
        {"id": "p", "name": "P", "type": "tool", "provides": ["status_tiles"]}
    )
    assert out["provides"] == ["status_tiles"]


def test_normalize_provides_not_list():
    """
    provides не список - приводится к пустому списку.
    Вход: dict с id="p", name="P", type="tool", provides="string".
    Выход: provides == [].
    """
    out = normalize_manifest(
        {"id": "p", "name": "P", "type": "tool", "provides": "string"}
    )
    assert out["provides"] == []

"""Unit tests: app.plugins.loader"""
import json

from app.plugins.loader import load_plugins_from_dir


def test_load_empty_dir(tmp_path):
    """
    Пустой каталог - пустой результат.
    Вход: существующая пустая директория tmp_path.
    Выход: [].
    """
    assert load_plugins_from_dir(str(tmp_path)) == []


def test_load_none_dir():
    """
    Путь None или пустая строка.
    Вход: None и "".
    Выход: [].
    """
    assert load_plugins_from_dir(None) == []
    assert load_plugins_from_dir("") == []


def test_load_nonexistent_dir():
    """
    Несуществующий путь на диске.
    Вход: каталог, которого нет.
    Выход: [].
    """
    assert load_plugins_from_dir("/nonexistent_path_xyz") == []


def test_load_plugin_json_in_root(tmp_path):
    """
    Файл *.plugin.json в корне каталога.
    Вход: один JSON с полями id, name, type.
    Выход: список из одного элемента; id="a".
    """
    p = tmp_path / "test.plugin.json"
    p.write_text(
        json.dumps({"id": "a", "name": "A", "type": "tool"}),
        encoding="utf-8",
    )
    loaded = load_plugins_from_dir(str(tmp_path))
    assert len(loaded) == 1
    assert loaded[0]["id"] == "a"


def test_load_manifest_in_subdir(tmp_path):
    """
    manifest.json во вложенной папке.
    Вход: подкаталог с manifest.json.
    Выход: в списке есть плагин с id="b".
    """
    sub = tmp_path / "myplugin"
    sub.mkdir()
    (sub / "manifest.json").write_text(
        json.dumps({"id": "b", "name": "B", "type": "tool"}),
        encoding="utf-8",
    )
    loaded = load_plugins_from_dir(str(tmp_path))
    assert any(x["id"] == "b" for x in loaded)


def test_load_invalid_json_skipped(tmp_path):
    """
    Невалидный JSON - файл пропускается, без исключения.
    Вход: файл с синтаксически неверным JSON.   
    Выход: [].
    """
    p = tmp_path / "bad.plugin.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_plugins_from_dir(str(tmp_path)) == []


def test_load_dedup_by_id(tmp_path):
    """
    Два файла с одинаковым id - остаётся первый по порядку обхода.
    Вход: два *.plugin.json с id="dup", разные name.
    Выход: один элемент dup; name от первого файла ("One").
    """
    (tmp_path / "1.plugin.json").write_text(
        json.dumps({"id": "dup", "name": "One", "type": "tool"}),
        encoding="utf-8",
    )
    (tmp_path / "2.plugin.json").write_text(
        json.dumps({"id": "dup", "name": "Two", "type": "tool"}),
        encoding="utf-8",
    )
    loaded = load_plugins_from_dir(str(tmp_path))
    assert len([x for x in loaded if x["id"] == "dup"]) == 1
    assert loaded[0]["name"] == "One"

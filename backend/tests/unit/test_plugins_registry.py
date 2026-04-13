"""Unit tests: app.plugins.registry"""

from app.plugins.registry import get_plugin, list_plugins


def test_list_plugins_includes_system():
    """
    Встроенные плагины system_* присутствуют в списке.
    Вход: list_plugins(plugins_dir=None).
    Выход: В множестве id есть system_metrics и hardware.
    """
    plugs = list_plugins(plugins_dir=None)
    ids = {p["id"] for p in plugs}
    assert "system_metrics" in ids
    assert "hardware" in ids


def test_list_plugins_filter_by_provides():
    """
    Фильтр по provides.
    Вход: provides="status_tiles".
    Выход: ровно один плагин - system_metrics.
    """
    plugs = list_plugins(provides="status_tiles", plugins_dir=None)
    assert len(plugs) == 1
    assert plugs[0]["id"] == "system_metrics"


def test_get_plugin_system():
    """
    Загрузка встроенного плагина по id.
    Вход: id="system_metrics".
    Выход: dict не None; ожидаемое поле name.
    """
    p = get_plugin("system_metrics", plugins_dir=None)
    assert p is not None
    assert p["name"] == "System Metrics"


def test_get_plugin_not_found():
    """
    Несуществующий id.
    Вход: id="nonexistent".
    Выход: None.
    """
    assert get_plugin("nonexistent", plugins_dir=None) is None


def test_system_plugins_override_dir(tmp_path):
    """
    Файл в каталоге не подменяет встроенный манифест с тем же id.
    Вход: tmp_path с JSON id=system_metrics, name=Custom.
    Выход: get_plugin возвращает системное имя "System Metrics".
    """
    (tmp_path / "x.plugin.json").write_text(
        '{"id": "system_metrics", "name": "Custom", "type": "tool"}',
        encoding="utf-8",
    )
    p = get_plugin("system_metrics", plugins_dir=str(tmp_path))
    assert p is not None
    assert p["name"] == "System Metrics"

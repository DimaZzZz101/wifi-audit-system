"""Unit tests: app.services.session_tools"""
from app.services.session_tools import AVAILABLE_TOOLS, get_tool_definition, list_available_tools


def test_list_available_tools():
    """
    list_available_tools возвращает каталог инструментов.
    Вход: Вызов list_available_tools() без аргументов.
    Выход: Среди id есть wifi_info, wifi_setup, recon.
    """
    tools = list_available_tools()
    ids = {t["id"] for t in tools}
    assert "wifi_info" in ids
    assert "wifi_setup" in ids
    assert "recon" in ids


def test_get_tool_definition_exists():
    """
    Определение инструмента recon.
    Вход: get_tool_definition("recon").
    Выход: dict не None; есть ключи image и cap_add.
    """
    d = get_tool_definition("recon")
    assert d is not None
    assert "image" in d
    assert d.get("cap_add")


def test_get_tool_definition_unknown():
    """
    Неизвестный id инструмента.
    Вход: get_tool_definition("unknown").
    Выход: None.
    """
    assert get_tool_definition("unknown") is None


def test_recon_tool_has_net_admin():
    """
    У инструмента recon в cap_add есть NET_ADMIN.
    Вход: AVAILABLE_TOOLS["recon"]["cap_add"].
    Выход: "NET_ADMIN" входит в cap_add.
    """
    assert "NET_ADMIN" in AVAILABLE_TOOLS["recon"]["cap_add"]

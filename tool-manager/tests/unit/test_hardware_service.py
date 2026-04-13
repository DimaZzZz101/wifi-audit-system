"""Unit tests: app.hardware_service"""
from pathlib import Path

import pytest

from app import hardware_service


def test_get_network_interfaces(tmp_path, monkeypatch):
    """
    get_network_interfaces: wireless по наличию каталога .../wireless.

    Вход:
        Фейковое дерево tmp_path/sys/class/net с wlan0/wireless и eth0; Path и _run подменены.
    Выход:
        wlan0[\"wireless\"] is True; eth0[\"wireless\"] is False.
    """
    net = tmp_path / "sys" / "class" / "net"
    (net / "wlan0" / "wireless").mkdir(parents=True)
    (net / "eth0").mkdir(parents=True)

    orig = Path

    def fake_path(*args):
        if args == ("/sys/class/net",):
            return net
        return orig(*args)

    monkeypatch.setattr(hardware_service, "Path", fake_path)
    monkeypatch.setattr(hardware_service, "_run", lambda _: None)

    res = hardware_service.get_network_interfaces()
    by_name = {r["name"]: r for r in res}
    assert by_name["wlan0"]["wireless"] is True
    assert by_name["eth0"]["wireless"] is False


def test_get_network_interfaces_no_wifi(tmp_path, monkeypatch):
    """
    Только eth без wireless - помечается как не Wi-Fi.

    Вход:
        Только eth0 без подкаталога wireless.
    Выход:
        eth0[\"wireless\"] is False.
    """
    net = tmp_path / "sys" / "class" / "net"
    (net / "eth0").mkdir(parents=True)

    orig = Path

    def fake_path(*args):
        if args == ("/sys/class/net",):
            return net
        return orig(*args)

    monkeypatch.setattr(hardware_service, "Path", fake_path)
    monkeypatch.setattr(hardware_service, "_run", lambda _: None)

    res = hardware_service.get_network_interfaces()
    eth = next(x for x in res if x["name"] == "eth0")
    assert eth["wireless"] is False


def test_get_usb_devices(monkeypatch):
    """
    get_usb_devices парсит вывод lsusb.
    Вход: _run для lsusb возвращает строку с RTL8812AU.
    Выход: Непустой список; у первого элемента есть id.
    """
    sample = ["Bus 001 Device 002: ID 0bda:0812 Realtek Semiconductor Corp. RTL8812AU"]
    monkeypatch.setattr(
        hardware_service,
        "_run",
        lambda cmd: sample if cmd and cmd[0] == "lsusb" else None,
    )

    res = hardware_service.get_usb_devices()
    assert len(res) >= 1
    assert res[0]["id"]


def test_get_summary_combines_all(monkeypatch):
    """
    get_hardware_summary объединяет USB, PCI, сеть и ФС.
    Вход: Моки get_usb_devices, get_pci_devices, get_network_interfaces, get_filesystem_usage.
    Выход: Словарь с ключами usb_devices, pci_devices, network_interfaces, filesystem.
    """
    monkeypatch.setattr(
        hardware_service,
        "get_usb_devices",
        lambda: [{"bus": "1", "device": "1", "id": "0:0", "name": "x"}],
    )
    monkeypatch.setattr(hardware_service, "get_pci_devices", lambda: [])
    monkeypatch.setattr(
        hardware_service,
        "get_network_interfaces",
        lambda: [{"name": "wlan0", "flags": "", "wireless": True}],
    )
    monkeypatch.setattr(hardware_service, "get_filesystem_usage", lambda: [])

    s = hardware_service.get_hardware_summary()
    assert "usb_devices" in s
    assert "pci_devices" in s
    assert "network_interfaces" in s
    assert "filesystem" in s

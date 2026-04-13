"""REST API TOOL-manager: hardware (хост). Доступ к /sys и /dev/bus/usb хоста - только здесь."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import require_jwt
from app import hardware_service
from app.schemas import (
    UsbDevice,
    PciDevice,
    NetworkInterface,
    FilesystemUsage,
    HardwareSummary,
)

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("/summary", response_model=HardwareSummary)
async def hardware_summary(
    _payload: Annotated[dict, Depends(require_jwt)],
    wifi_only: bool = False,
) -> HardwareSummary:
    """Сводка по хосту: USB, PCI, сетевые интерфейсы, ФС. wifi_only=true - только Wi-Fi модули (USB/PCI)."""
    data = hardware_service.get_hardware_summary(wifi_only=wifi_only)
    return HardwareSummary(
        usb_devices=[UsbDevice(**d) for d in data["usb_devices"]],
        pci_devices=[PciDevice(**d) for d in data.get("pci_devices", [])],
        network_interfaces=[NetworkInterface(**d) for d in data["network_interfaces"]],
        filesystem=[FilesystemUsage(**d) for d in data["filesystem"]],
    )


@router.get("/usb", response_model=list[UsbDevice])
async def hardware_usb(
    _payload: Annotated[dict, Depends(require_jwt)],
) -> list[UsbDevice]:
    """Список USB-устройств (lsusb)."""
    devices = hardware_service.get_usb_devices()
    return [UsbDevice(**d) for d in devices]


@router.get("/network-interfaces", response_model=list[NetworkInterface])
async def hardware_network_interfaces(
    _payload: Annotated[dict, Depends(require_jwt)],
) -> list[NetworkInterface]:
    """Сетевые интерфейсы (в т.ч. Wi-Fi)."""
    interfaces = hardware_service.get_network_interfaces()
    return [NetworkInterface(**d) for d in interfaces]


@router.get("/pci", response_model=list[PciDevice])
async def hardware_pci(
    _payload: Annotated[dict, Depends(require_jwt)],
    wifi_only: bool = False,
) -> list[PciDevice]:
    """Список PCI-устройств (lspci). wifi_only - только Wi-Fi модули."""
    devices = hardware_service.get_pci_devices()
    if wifi_only:
        devices = [d for d in devices if d.get("wifi_capable")]
    return [PciDevice(**d) for d in devices]


@router.get("/filesystem", response_model=list[FilesystemUsage])
async def hardware_filesystem(
    _payload: Annotated[dict, Depends(require_jwt)],
) -> list[FilesystemUsage]:
    """Использование файловых систем (df)."""
    fs = hardware_service.get_filesystem_usage()
    return [FilesystemUsage(**d) for d in fs]

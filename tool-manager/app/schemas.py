"""Схемы запросов/ответов TOOL-manager (совместимы с API-Gateway)."""
from pydantic import BaseModel, Field


class ContainerCreate(BaseModel):
    image: str = Field(..., min_length=1)
    name: str | None = Field(None, max_length=128)
    container_type: str | None = Field(None, max_length=32)
    env: dict[str, str] | None = None
    network_mode: str | None = "host"
    cap_add: list[str] | None = None
    volumes: list[str] | None = None
    command: str | list[str] | None = None
    detach: bool = True


class ContainerItem(BaseModel):
    id: str
    short_id: str
    name: str
    image: str
    status: str
    created: str
    labels: dict[str, str] | None = None


class ContainerCreated(BaseModel):
    id: str | None = None
    short_id: str | None = None
    name: str | None = None
    image: str
    status: str
    created: str | None = None


class ContainerStopped(BaseModel):
    id: str
    stopped: bool = True
    removed: bool = True


class ImagePullBody(BaseModel):
    image: str = Field(..., min_length=1)


class ImageItem(BaseModel):
    """Образ из реестра Docker (для страницы Реестр)."""
    id: str
    tags: list[str]
    created: str = ""
    size: int = 0


# Hardware (host info: USB, PCI, network interfaces, filesystem). Same shape as API-Gateway.
class UsbDevice(BaseModel):
    bus: str
    device: str
    id: str
    name: str
    wifi_capable: bool = False


class PciDevice(BaseModel):
    slot: str
    class_name: str
    name: str
    wifi_capable: bool = False


class NetworkInterface(BaseModel):
    name: str
    flags: str = ""
    wireless: bool = False


class FilesystemUsage(BaseModel):
    filesystem: str
    type: str
    size: str
    used: str
    available: str
    use_percent: str
    mounted_on: str


class HardwareSummary(BaseModel):
    usb_devices: list[UsbDevice] = []
    pci_devices: list[PciDevice] = []
    network_interfaces: list[NetworkInterface] = []
    filesystem: list[FilesystemUsage] = []

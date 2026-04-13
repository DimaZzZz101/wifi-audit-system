"""Schemas для модуля Hardware (информация о хосте для Wi-Fi аудита)."""
import re

from pydantic import BaseModel, Field, field_validator

MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


class UsbDevice(BaseModel):
    """USB-устройство (lsusb)."""
    bus: str = Field(..., description="Номер шины")
    device: str = Field(..., description="Номер устройства")
    id: str = Field(..., description="ID производителя:продукт (xxxx:yyyy)")
    name: str = Field(..., description="Описание устройства")
    wifi_capable: bool = Field(False, description="Подходит для Wi-Fi (адаптер)")


class PciDevice(BaseModel):
    """PCI-устройство (lspci)."""
    slot: str = Field(..., description="Слот (например 02:00.0)")
    class_name: str = Field(..., description="Класс устройства")
    name: str = Field(..., description="Описание")
    wifi_capable: bool = Field(False, description="Подходит для Wi-Fi (сетевой контроллер)")


class NetworkInterface(BaseModel):
    """Сетевой интерфейс (в т.ч. беспроводной wlan*)."""
    name: str = Field(..., description="Имя интерфейса")
    flags: str = Field("", description="Флаги (UP, LOWER_UP и т.д.)")
    wireless: bool = Field(False, description="Беспроводной интерфейс (Wi-Fi)")


class FilesystemUsage(BaseModel):
    """Строка df: использование файловой системы."""
    filesystem: str = Field(..., description="Устройство или точка монтирования")
    type: str = Field(..., description="Тип ФС (ext4, tmpfs и т.д.)")
    size: str = Field(..., description="Размер (человекочитаемый)")
    used: str = Field(..., description="Использовано")
    available: str = Field(..., description="Доступно")
    use_percent: str = Field(..., description="Процент использования")
    mounted_on: str = Field(..., description="Точка монтирования")


class HardwareSummary(BaseModel):
    """Сводка по хосту: USB, PCI, сетевые интерфейсы, файловые системы."""
    usb_devices: list[UsbDevice] = Field(default_factory=list, description="USB-устройства")
    pci_devices: list[PciDevice] = Field(default_factory=list, description="PCI-устройства")
    network_interfaces: list[NetworkInterface] = Field(default_factory=list, description="Сетевые интерфейсы")
    filesystem: list[FilesystemUsage] = Field(default_factory=list, description="Использование ФС")


# ---------------------------------------------------------------------------
# Wi-Fi adapter state / configure
# ---------------------------------------------------------------------------

class SupportedChannel(BaseModel):
    """Канал, поддерживаемый физическим устройством."""
    channel: int
    freq: int = Field(description="Частота в МГц")
    band: str = Field(description="2.4 или 5")
    max_power_dbm: float | None = Field(None, description="Макс. мощность (dBm)")
    dfs: bool = Field(False, description="Требуется DFS (radar detection)")
    disabled: bool = Field(False, description="Запрещён регулятором")


class WifiAdapterState(BaseModel):
    """Расширенное состояние Wi-Fi интерфейса (из wifi-setup MODE=info)."""
    mode: str = Field("", description="Текущий режим (managed/monitor)")
    channel: int | None = Field(None, description="Текущий канал")
    freq: int | None = Field(None, description="Текущая частота (МГц)")
    txpower: float | None = Field(None, description="Текущая мощность TX (dBm)")
    mac: str | None = Field(None, description="MAC-адрес")
    phy: str = Field("", description="Имя физического устройства (phy0)")
    reg_domain: str = Field("", description="Регуляторный домен (RU, US, ...)")
    supported_channels: list[SupportedChannel] = Field(default_factory=list)


class WifiAdapterConfigureBody(BaseModel):
    """Тело запроса на настройку Wi-Fi адаптера."""
    mode: str = Field(..., description="monitor или managed")
    channel: int | None = Field(None, ge=1, description="Номер канала")
    txpower: int | None = Field(None, ge=0, le=23, description="Мощность TX (dBm). РФ: макс. 20 (2.4 ГГц), 23 (5 ГГц)")
    mac: str | None = Field(None, description="MAC-адрес XX:XX:XX:XX:XX:XX")

    @field_validator("mac")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        if v is not None and not MAC_RE.match(v):
            raise ValueError("Invalid MAC format, expected XX:XX:XX:XX:XX:XX")
        return v

"""Модуль Hardware: информация о хосте (USB, сетевые интерфейсы, ФС) для Wi-Fi аудита."""
import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_user, get_bearer_token
from app.models.user import User
from app.schemas.hardware import (
    UsbDevice,
    PciDevice,
    NetworkInterface,
    FilesystemUsage,
    HardwareSummary,
    WifiAdapterState,
    WifiAdapterConfigureBody,
    SupportedChannel,
)
from app.services import hardware_service
from app.services import session_tools
from app.services import tool_manager_client

router = APIRouter(prefix="/hardware", tags=["hardware"])

INTERFACE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@router.get(
    "/summary",
    response_model=HardwareSummary,
    summary="Сводка по хосту",
    description="USB, PCI, сетевые интерфейсы, ФС. wifi_only=true - только Wi-Fi модули (USB/PCI). В Docker данные с хоста через TOOL-manager.",
)
async def hardware_summary(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    wifi_only: bool = False,
) -> HardwareSummary:
    token = get_bearer_token(request)
    data = await tool_manager_client.tool_manager_hardware_summary(token, wifi_only=wifi_only)
    if data is None:
        data = hardware_service.get_hardware_summary(wifi_only=wifi_only)
    return HardwareSummary(
        usb_devices=[UsbDevice(**d) for d in data["usb_devices"]],
        pci_devices=[PciDevice(**d) for d in data.get("pci_devices", [])],
        network_interfaces=[NetworkInterface(**d) for d in data["network_interfaces"]],
        filesystem=[FilesystemUsage(**d) for d in data["filesystem"]],
    )


@router.get(
    "/usb",
    response_model=list[UsbDevice],
    summary="USB-устройства",
)
async def hardware_usb(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    wifi_only: bool = False,
) -> list[UsbDevice]:
    token = get_bearer_token(request)
    data = await tool_manager_client.tool_manager_hardware_summary(token, wifi_only=wifi_only)
    devices = [d for d in (data or {}).get("usb_devices", [])] if data else None
    if devices is None:
        devices = hardware_service.get_usb_devices()
        if wifi_only:
            devices = [d for d in devices if d.get("wifi_capable")]
    return [UsbDevice(**d) for d in devices]


@router.get(
    "/pci",
    response_model=list[PciDevice],
    summary="PCI-устройства",
)
async def hardware_pci(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    wifi_only: bool = False,
) -> list[PciDevice]:
    token = get_bearer_token(request)
    data = await tool_manager_client.tool_manager_hardware_summary(token, wifi_only=wifi_only)
    devices = [d for d in (data or {}).get("pci_devices", [])] if data else None
    if devices is None:
        devices = hardware_service.get_pci_devices()
        if wifi_only:
            devices = [d for d in devices if d.get("wifi_capable")]
    return [PciDevice(**d) for d in devices]


@router.get(
    "/network-interfaces",
    response_model=list[NetworkInterface],
    summary="Сетевые интерфейсы",
)
async def hardware_network_interfaces(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> list[NetworkInterface]:
    token = get_bearer_token(request)
    data = await tool_manager_client.tool_manager_hardware_summary(token)
    interfaces = [d for d in (data or {}).get("network_interfaces", [])] if data else None
    if interfaces is None:
        interfaces = hardware_service.get_network_interfaces()
    return [NetworkInterface(**d) for d in interfaces]


@router.get(
    "/filesystem",
    response_model=list[FilesystemUsage],
    summary="Файловые системы",
)
async def hardware_filesystem(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> list[FilesystemUsage]:
    token = get_bearer_token(request)
    data = await tool_manager_client.tool_manager_hardware_summary(token)
    fs = [d for d in (data or {}).get("filesystem", [])] if data else None
    if fs is None:
        fs = hardware_service.get_filesystem_usage()
    return [FilesystemUsage(**d) for d in fs]


def _validate_interface_name(name: str) -> None:
    if not name or not INTERFACE_NAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid interface name",
        )


def _get_wifi_setup_tool() -> dict:
    tool = session_tools.get_tool_definition("wifi_setup")
    if not tool:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="wifi_setup tool not configured")
    return tool


def _parse_tool_stdout(raw: dict) -> dict:
    """Parse tool run result, raise on error."""
    stdout = raw.get("stdout", "")
    if raw.get("exit_code") != 0:
        try:
            err = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            err = {}
        detail = err.get("error") or raw.get("stderr") or "Tool execution failed"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid tool output")


@router.get(
    "/wifi-adapter/{name}/state",
    response_model=WifiAdapterState,
    summary="Состояние Wi-Fi адаптера",
    description="Расширенная информация: режим, канал, частота, мощность, MAC, поддерживаемые каналы.",
)
async def hardware_wifi_adapter_state(
    request: Request,
    name: str,
    current_user: Annotated[User, Depends(require_user)],
) -> WifiAdapterState:
    _validate_interface_name(name)
    tool = _get_wifi_setup_tool()
    token = get_bearer_token(request)
    raw = await tool_manager_client.tool_manager_run_tool(
        token=token,
        image=tool["image"],
        env={"INTERFACE": name, "MODE": "info"},
        network_mode=tool["network_mode"],
        cap_add=tool.get("cap_add"),
        timeout=tool.get("timeout", 30),
    )
    data = _parse_tool_stdout(raw)
    channels = [SupportedChannel(**ch) for ch in data.get("supported_channels", [])]
    return WifiAdapterState(
        mode=data.get("mode", ""),
        channel=data.get("channel"),
        freq=data.get("freq"),
        txpower=data.get("txpower"),
        mac=data.get("mac"),
        phy=data.get("phy", ""),
        reg_domain=data.get("reg_domain", ""),
        supported_channels=channels,
    )


@router.post(
    "/wifi-adapter/{name}/configure",
    summary="Настроить Wi-Fi адаптер",
    description="Установить режим, канал, TX power, MAC. Идемпотентно.",
)
async def hardware_wifi_adapter_configure(
    request: Request,
    name: str,
    body: WifiAdapterConfigureBody,
    current_user: Annotated[User, Depends(require_user)],
) -> dict:
    _validate_interface_name(name)
    if body.mode not in ("monitor", "managed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mode must be monitor or managed",
        )
    tool = _get_wifi_setup_tool()
    token = get_bearer_token(request)
    env: dict[str, str] = {"INTERFACE": name, "MODE": body.mode}
    if body.mode == "monitor":
        if body.channel is not None:
            env["CHANNEL"] = str(body.channel)
        if body.txpower is not None:
            env["TXPOWER"] = str(body.txpower)
    if body.mac is not None:
        env["MAC"] = body.mac
    raw = await tool_manager_client.tool_manager_run_tool(
        token=token,
        image=tool["image"],
        env=env,
        network_mode=tool["network_mode"],
        cap_add=tool.get("cap_add"),
        timeout=tool.get("timeout", 30),
    )
    return _parse_tool_stdout(raw)



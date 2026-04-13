"""Установленные модули, каталог доступных, скачивание и установка/удаление."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_user, audit
from app.models.user import User
from app.schemas.modules import (
    InstalledModule,
    AvailableModule,
    ModuleDownloadRequest,
    ModuleInstallRequest,
    ModuleInstallResponse,
    ModuleDownloadStatus,
)
from app.services import module_install_service

router = APIRouter(prefix="/modules", tags=["modules"])


def _module_install_error_status(err: str) -> int:
    msg = (err or "").lower()
    if "no downloaded package" in msg or "downloaded file not found" in msg:
        return status.HTTP_409_CONFLICT
    if "plugins_dir is not configured" in msg:
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    if (
        "checksum mismatch" in msg
        or "invalid archive" in msg
        or "archive is empty" in msg
        or "invalid module id" in msg
        or "manifest not found" in msg
        or "no manifest" in msg
    ):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


@router.get(
    "/installed",
    response_model=list[InstalledModule],
    summary="Установленные модули",
    description="Список установленных модулей (из каталога + встроенные). Поле removable - можно ли удалить.",
)
async def modules_installed(
    current_user: Annotated[User, Depends(require_user)],
) -> list[InstalledModule]:
    items = module_install_service.get_installed_modules()
    return [InstalledModule(**m) for m in items]


@router.get(
    "/available",
    response_model=list[AvailableModule],
    summary="Доступные для установки модули",
    description="Список модулей из удалённого каталога (MODULES_INDEX_URL). Пусто, если URL не задан.",
)
async def modules_available(
    current_user: Annotated[User, Depends(require_user)],
) -> list[AvailableModule]:
    items = await module_install_service.fetch_available_modules()
    return [AvailableModule(**m) for m in items]


@router.post(
    "/download",
    summary="Скачать пакет модуля",
    description="Скачивает .tar.gz по URL во временный каталог. Затем вызовите POST /api/modules/install.",
)
async def module_download(
    request: Request,
    body: ModuleDownloadRequest,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    path, err = await module_install_service.download_module(body.download_url)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    await audit(
        db,
        user_id=current_user.id,
        action="module.download",
        request=request,
        resource_type="module",
        resource_id=path or "",
        details={"download_url": body.download_url},
    )
    await db.commit()
    return {"success": True, "message": "Downloaded. Call POST /api/modules/install to install."}


@router.get(
    "/download-status",
    response_model=ModuleDownloadStatus,
    summary="Статус скачивания",
)
async def module_download_status(
    current_user: Annotated[User, Depends(require_user)],
) -> ModuleDownloadStatus:
    st = module_install_service.get_download_status()
    # Не раскрываем внутренние пути ФС в API-ответе.
    return ModuleDownloadStatus(success=st["success"], path=None)


@router.post(
    "/install",
    response_model=ModuleInstallResponse,
    summary="Установить скачанный модуль",
    description="Распаковывает ранее скачанный пакет в PLUGINS_DIR. Опционально проверяет checksum (sha256).",
)
async def module_install(
    request: Request,
    body: ModuleInstallRequest,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ModuleInstallResponse:
    module_id, err = module_install_service.install_downloaded_module(checksum=body.checksum)
    if err:
        raise HTTPException(status_code=_module_install_error_status(err), detail=err)
    if not module_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Module install failed")
    await audit(
        db,
        user_id=current_user.id,
        action="module.install",
        request=request,
        resource_type="module",
        resource_id=module_id or "",
        details={"checksum": body.checksum},
    )
    await db.commit()
    return ModuleInstallResponse(module_id=module_id)


@router.delete(
    "/{module_id}",
    summary="Удалить установленный модуль",
    description="Удаляет модуль из каталога плагинов. Системные модули удалить нельзя.",
)
async def module_remove(
    module_id: str,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    success, err = module_install_service.remove_module(module_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST if "Cannot remove" in (err or "") else status.HTTP_404_NOT_FOUND,
            detail=err or "Failed to remove",
        )
    await audit(
        db,
        user_id=current_user.id,
        action="module.remove",
        request=request,
        resource_type="module",
        resource_id=module_id,
    )
    await db.commit()
    return {"success": True, "module_id": module_id}

"""API проектов аудита Wi-Fi."""
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_bearer_token, require_user, audit
from app.models.audit import AuditPlan
from app.models.user import User
from app.models.project import Project
from app.schemas.sessions import MacFilterBody, MacFilterResponse, ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.audit_storage import build_audit_display_name, build_audit_storage_dirname
from app.services.session_service import ensure_project_dirs, remove_project_dir, resolve_project_path, write_mac_filter_file
from app.services import session_tools

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectResponse],
    summary="Список проектов аудита",
)
async def projects_list(
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectResponse]:
    """Получить список всех проектов аудита."""
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект аудита",
)
async def project_create(
    request: Request,
    body: ProjectCreate,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    """Создать новый проект аудита. Создаётся запись в БД и файловая структура. Имя должно быть уникальным."""
    name = body.name.strip()
    existing = await db.execute(select(Project).where(Project.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Проект с именем "{name}" уже существует. Выберите другое имя.',
        )
    slug = secrets.token_hex(6)
    project = Project(
        slug=slug,
        name=name,
        status="inactive",
        session_type="audit",
    )
    db.add(project)
    await db.flush()

    try:
        ensure_project_dirs(slug)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Не удалось создать директорию проекта: {e}",
        )

    await db.commit()
    await db.refresh(project)

    await audit(
        db,
        user_id=current_user.id,
        action="project.create",
        request=request,
        resource_type="project",
        resource_id=str(project.id),
        details={"name": project.name},
    )

    return ProjectResponse.model_validate(project)


@router.get(
    "/{project_id:int}",
    response_model=ProjectResponse,
    summary="Получить проект по id",
)
async def project_get(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    """Получить проект по id."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id:int}",
    response_model=ProjectResponse,
    summary="Обновить проект (активировать)",
)
async def project_update(
    project_id: int,
    request: Request,
    body: ProjectUpdate,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    """Активировать проект (status=active) или обновить другие поля."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    if body.status is not None:
        project.status = body.status
    if body.name is not None:
        project.name = body.name.strip()[:256]
    if body.obfuscation_enabled is not None:
        project.obfuscation_enabled = body.obfuscation_enabled

    await db.commit()
    await db.refresh(project)

    if body.status is not None:
        await audit(
            db,
            user_id=current_user.id,
            action="project.activate" if body.status == "active" else "project.update",
            request=request,
            resource_type="project",
            resource_id=str(project_id),
            details={"name": project.name, "status": project.status},
        )

    return ProjectResponse.model_validate(project)


import re as _re
_MAC_RE = _re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


@router.get(
    "/{project_id:int}/mac-filter",
    response_model=MacFilterResponse,
    summary="Get MAC filter for project",
)
async def mac_filter_get(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MacFilterResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return MacFilterResponse(
        filter_type=project.mac_filter_type,
        entries=project.mac_filter_entries or [],
    )


@router.put(
    "/{project_id:int}/mac-filter",
    response_model=MacFilterResponse,
    summary="Save MAC filter for project",
)
async def mac_filter_put(
    project_id: int,
    request: Request,
    body: MacFilterBody,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MacFilterResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    cleaned: list[str] = []
    for raw in body.entries:
        mac = raw.strip().upper()
        if mac and _MAC_RE.match(mac):
            cleaned.append(mac)

    project.mac_filter_type = body.filter_type
    project.mac_filter_entries = cleaned
    await db.commit()
    await db.refresh(project)

    write_mac_filter_file(project.slug, cleaned)

    await audit(
        db,
        user_id=current_user.id,
        action="project.mac_filter.update",
        request=request,
        resource_type="project",
        resource_id=str(project_id),
        details={"filter_type": body.filter_type, "count": len(cleaned)},
    )

    return MacFilterResponse(filter_type=project.mac_filter_type, entries=cleaned)


@router.get(
    "/{project_id:int}/mac-filter/file",
    summary="Download mac_filter.txt",
)
async def mac_filter_file_download(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    fpath = resolve_project_path(project.slug, "mac_filter.txt")
    if not fpath or not fpath.exists():
        entries = project.mac_filter_entries or []
        fpath = write_mac_filter_file(project.slug, entries)

    return FileResponse(fpath, filename="mac_filter.txt", media_type="text/plain")


@router.get(
    "/{project_id:int}/files",
    summary="Список файлов проекта",
)
async def project_files_list(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    path: str = "",
) -> dict:
    """Список файлов и папок в директории проекта."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    resolved = resolve_project_path(project.slug, path)
    if not resolved or not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Путь не найден")
    if not resolved.is_dir():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ожидается директория")

    audit_dir_labels: dict[str, str] = {}
    normalized_path = path.strip("/")
    if normalized_path == "audits":
        plans_row = await db.execute(
            select(AuditPlan).where(AuditPlan.project_id == project.id)
        )
        for plan in plans_row.scalars().all():
            label = build_audit_display_name(
                plan_id=plan.id,
                created_at=plan.created_at,
                essid=plan.essid,
                bssid=plan.bssid,
            )
            audit_dir_labels[str(plan.id)] = label
            audit_dir_labels[
                build_audit_storage_dirname(
                    plan_id=plan.id,
                    created_at=plan.created_at,
                    essid=plan.essid,
                    bssid=plan.bssid,
                )
            ] = label

    items: list[dict] = []
    for p in sorted(resolved.iterdir()):
        try:
            stat = p.stat()
            item = {
                "name": p.name,
                "path": path + ("/" if path else "") + p.name,
                "is_dir": p.is_dir(),
                "size": stat.st_size if p.is_file() else None,
            }
            display_name = audit_dir_labels.get(p.name)
            if display_name:
                item["display_name"] = display_name
            items.append(item)
        except OSError:
            continue

    return {"path": path or ".", "items": items}


@router.get(
    "/{project_id:int}/files/content",
    summary="Содержимое файла (для просмотра)",
)
async def project_file_content(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    path: str = Query(..., description="Относительный путь к файлу"),
):
    """Получить содержимое файла как текст (для небольших файлов)."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    resolved = resolve_project_path(project.slug, path)
    if not resolved or not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(content)
    except OSError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось прочитать файл")


@router.get(
    "/{project_id:int}/files/download",
    summary="Скачать файл",
)
async def project_file_download(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    path: str = Query(..., description="Относительный путь к файлу"),
):
    """Скачать файл проекта."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    resolved = resolve_project_path(project.slug, path)
    if not resolved or not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    return FileResponse(resolved, filename=resolved.name)


@router.delete(
    "/{project_id:int}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить проект",
)
async def project_delete(
    project_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Удалить проект: запись в БД и директорию с артефактами на volume."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    slug = project.slug
    name = project.name

    await db.delete(project)
    await db.commit()

    remove_project_dir(slug)

    await audit(
        db,
        user_id=current_user.id,
        action="project.delete",
        request=request,
        resource_type="project",
        resource_id=str(project_id),
        details={"name": name},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Project tools
# ---------------------------------------------------------------------------


class ToolRunRequest(BaseModel):
    tool_id: str = Field(..., min_length=1)


@router.get(
    "/{project_id:int}/tools/available",
    summary="Доступные инструменты",
)
async def project_tools_available(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict[str, Any]]:
    """Список доступных инструментов для запуска в проекте."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project_obj = result.scalar_one_or_none()
    if not project_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return session_tools.list_available_tools()


@router.post(
    "/{project_id:int}/tools/run",
    summary="Запустить инструмент в проекте",
)
async def project_tool_run(
    project_id: int,
    request: Request,
    body: ToolRunRequest,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Запустить tool-контейнер в контексте проекта. Проект должен быть активен."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project_obj = result.scalar_one_or_none()
    if not project_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    if project_obj.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Проект не активен. Активируйте проект перед запуском инструмента.",
        )

    tool_def = session_tools.get_tool_definition(body.tool_id)
    if not tool_def:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Неизвестный инструмент: {body.tool_id}")

    token = get_bearer_token(request)

    try:
        tool_result = await session_tools.run_session_tool(
            token=token,
            slug=project_obj.slug,
            tool_id=body.tool_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Ошибка запуска инструмента: {e}",
        )

    await audit(
        db,
        user_id=current_user.id,
        action="project_tool.run",
        request=request,
        resource_type="project",
        resource_id=str(project_id),
        details={"tool_id": body.tool_id, "exit_code": tool_result.get("exit_code")},
    )

    return tool_result


@router.get(
    "/{project_id:int}/tools/runs",
    summary="История запусков инструментов",
)
async def project_tool_runs(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict[str, Any]]:
    """Список предыдущих запусков инструментов проекта (из results/)."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project_obj = result.scalar_one_or_none()
    if not project_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return session_tools.list_tool_runs(project_obj.slug)

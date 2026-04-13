"""Getting Started / first-run: check status, create first user."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, audit
from app.models.user import User
from app.schemas.setup import SetupStatus, SetupCreateUser
from app.schemas.auth import Token
from app.core.security import get_password_hash, create_access_token

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get(
    "/status",
    response_model=SetupStatus,
    summary="Статус первого запуска",
    description="""
    Проверяет, завершена ли первоначальная настройка системы.

    Если `setup_completed = false`, нужно вызвать `/api/setup/create-user` для создания первого пользователя.
    После создания хотя бы одного пользователя `setup_completed` становится `true`.
    """,
    responses={
        200: {
            "description": "Статус настройки",
            "content": {
                "application/json": {
                    "example": {"setup_completed": False}
                }
            },
        },
    },
)
async def get_setup_status(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SetupStatus:
    """
    Проверить статус первоначальной настройки.

    **Пример ответа (первый запуск):**
    ```json
    {
      "setup_completed": false
    }
    ```

    **Пример ответа (настройка завершена):**
    ```json
    {
      "setup_completed": true
    }
    ```
    """
    result = await db.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    return SetupStatus(setup_completed=user is not None)


@router.post(
    "/create-user",
    response_model=Token,
    summary="Создание первого пользователя",
    description="""
    Создаёт первого пользователя системы (Getting Started).

    Доступно только если в системе ещё нет пользователей (`setup_completed = false`).
    После создания пользователя система считается настроенной, и этот эндпоинт больше недоступен.

    Возвращает JWT токен для немедленного входа.
    """,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "Пользователь создан, возвращён токен",
            "content": {
                "application/json": {
                    "example": {"access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
                }
            },
        },
        400: {"description": "Настройка уже завершена, используйте /api/auth/login"},
    },
)
async def create_first_user(
    request: Request,
    body: SetupCreateUser,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Token:
    """
    Создать первого пользователя системы.

    **Пример запроса:**
    ```json
    {
      "username": "admin",
      "password": "secure_password"
    }
    ```

    **Пример ответа:**
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
    ```
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        # Сериализуем bootstrap-процедуру, чтобы исключить гонку "двойного первого пользователя".
        await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 9137001})

    result = await db.execute(select(User).limit(1))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup already completed. Use /auth/login.",
        )
    user = User(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await audit(
        db,
        user_id=user.id,
        action="setup.create_user",
        request=request,
        resource_type="user",
        resource_id=str(user.id),
        details={"username": body.username},
    )
    await db.commit()
    token = create_access_token(user.id)
    return Token(access_token=token)

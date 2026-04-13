"""Auth: login, token validation."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, audit, require_user
from app.models.user import User
from app.schemas.auth import UserCreate, UserResponse, Token, ChangePasswordBody
from app.core.security import verify_password, get_password_hash, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(UserCreate):
    pass


@router.post(
    "/login",
    response_model=Token,
    summary="Вход в систему",
    description="""
    Аутентификация пользователя по логину и паролю.

    Возвращает JWT токен, который нужно использовать в заголовке `Authorization: Bearer <token>`
    для доступа к защищённым эндпоинтам.

    Действие логируется в аудит-лог.
    """,
    responses={
        200: {
            "description": "Успешный вход, возвращён токен",
            "content": {
                "application/json": {
                    "example": {"access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
                }
            },
        },
        401: {"description": "Неверный логин или пароль"},
        403: {"description": "Пользователь отключён"},
    },
)
async def login(
    request: Request,
    body: LoginBody,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Token:
    """
    Вход в систему.

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
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled",
        )
    await audit(
        db,
        user_id=user.id,
        action="auth.login",
        request=request,
        resource_type="user",
        resource_id=str(user.id),
    )
    await db.commit()
    return Token(access_token=create_access_token(user.id))


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Текущий пользователь",
    description="""
    Возвращает информацию о текущем аутентифицированном пользователе.

    Требует JWT токен в заголовке `Authorization: Bearer <token>`.
    """,
    responses={
        200: {"description": "Информация о пользователе"},
        401: {"description": "Токен отсутствует или невалиден"},
    },
)
async def me(
    current_user: Annotated[User, Depends(require_user)],
) -> UserResponse:
    """
    Получить информацию о текущем пользователе.

    **Пример ответа:**
    ```json
    {
      "id": 1,
      "username": "admin",
      "is_active": true
    }
    ```
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        is_active=current_user.is_active,
    )


@router.post(
    "/change-password",
    summary="Смена пароля",
    description="Смена пароля текущего пользователя. Требует текущий пароль для подтверждения.",
    responses={
        200: {"description": "Пароль успешно обновлён"},
        400: {"description": "Неверный текущий пароль"},
        401: {"description": "Токен отсутствует или невалиден"},
    },
)
async def change_password(
    body: ChangePasswordBody,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> dict:
    """Change password for the current user."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль",
        )
    current_user.hashed_password = get_password_hash(body.new_password)
    db.add(current_user)
    await audit(
        db,
        user_id=current_user.id,
        action="auth.change_password",
        request=request,
        resource_type="user",
        resource_id=str(current_user.id),
    )
    await db.commit()
    return {"message": "Пароль успешно обновлён"}

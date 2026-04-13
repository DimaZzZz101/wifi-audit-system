"""FastAPI application - API Gateway. Доступ к Docker только через TOOL-manager."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine
from app.api.routes import setup, auth, containers, metrics, plugins, modules, hardware, registry, projects, recon, audit, dictionaries, audit_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.dictionary_service import cleanup_orphan_files
    try:
        removed = await cleanup_orphan_files()
        if removed:
            import logging
            logging.getLogger(__name__).info("Cleaned up %d orphan dictionary files", removed)
    except Exception:
        pass
    yield
    from app.services.recon_service import shutdown_all_sync_tasks
    from app.services.attack_service import shutdown_all_attack_tasks
    from app.services.dictionary_service import shutdown as dict_shutdown
    from app.services.tool_manager_client import close_client as close_tm_client
    await shutdown_all_sync_tasks()
    await shutdown_all_attack_tasks()
    await dict_shutdown()
    await close_tm_client()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="""
    **WiFi Audit API Gateway** - управляющая плоскость системы аудита WiFi.

    ## Архитектура

    Система состоит из двух плоскостей:
    - **Управляющая (API Gateway)**: Frontend -> API Gateway -> БД / cAdvisor / TOOL-manager
    - **Системная (TOOL-manager)**: единственный сервис с доступом к docker.sock

    ## Аутентификация

    Большинство эндпоинтов требуют JWT токен в заголовке:
    ```
    Authorization: Bearer <token>
    ```

    Получить токен можно через `/api/auth/login` или `/api/setup/create-user` (первый запуск).

    ## Основные разделы

    - **Setup** (`/api/setup/*`): первый запуск, создание пользователя
    - **Auth** (`/api/auth/*`): вход, получение текущего пользователя
    - **Containers** (`/api/containers/*`): управление контейнерами (прокси в TOOL-manager)
    - **Metrics** (`/api/metrics/*`): метрики хоста и системных контейнеров (cAdvisor)
    - **Plugins** (`/api/plugins/*`): список плагинов и их возможности

    ## Документация

    - **Swagger UI**: `/docs` (интерактивная документация)
    - **ReDoc**: `/redoc` (альтернативная документация)
    """,
    version="0.1.0",
    lifespan=lifespan,
    contact={
        "name": "WiFi Audit Project",
    },
    license_info={
        "name": "MIT",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(containers.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(modules.router, prefix="/api")
app.include_router(hardware.router, prefix="/api")
app.include_router(registry.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(recon.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(dictionaries.router, prefix="/api")
app.include_router(audit_settings.router, prefix="/api")


@app.get("/")
async def root():
    """Корень API: подсказка, чтобы не получать 404 в браузере."""
    return {
        "message": "WiFi Audit API Gateway",
        "docs": "/docs",
        "health": "/health",
        "api": "/api",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}

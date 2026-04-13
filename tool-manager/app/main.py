"""TOOL-manager: REST-сервис управления контейнерами. Доступ к docker.sock только здесь."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import router
from app.routes_hardware import router as hardware_router
from app.routes_tools import router as tools_router

settings = get_settings()

app = FastAPI(
    title="WiFi Audit TOOL-manager",
    description="Управление контейнерами с инструментами. Вызывается только API-Gateway по JWT.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(hardware_router)
app.include_router(tools_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

"""Реестр образов WiFi Audit - образы, разрешённые для служебных и инструментальных контейнеров."""
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RegistryImage(Base):
    """
    Образ, входящий в реестр WiFi Audit.
    В разделе "Реестр" и при создании служебных/инструментальных контейнеров
    используются только образы из этой таблицы. Системные образы (db, api, frontend, tool-manager)
    в реестр не входят.
    """
    __tablename__ = "registry_image"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    image_reference: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

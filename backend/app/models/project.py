"""Project  -  проект аудита Wi-Fi (группа сессий и артефактов)."""
from datetime import datetime
from sqlalchemy import Boolean, String, DateTime, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Project(Base):
    """Проект аудита: контейнер для проведения аудита Wi-Fi.

    Артефакты проекта (pcap, handshakes, логи, результаты) хранятся в
    ARTIFACTS_DIR/projects/{slug}/ - см. project_service.
    """
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    session_type: Mapped[str] = mapped_column(String(64), nullable=False, default="audit")

    mac_filter_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mac_filter_entries: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    obfuscation_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)

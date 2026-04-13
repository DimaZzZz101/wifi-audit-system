"""Unit tests: app.core.audit (log_audit)"""
import pytest
from sqlalchemy import select

from app.core.audit import log_audit
from app.models.audit_log import AuditLog
from app.models.user import User
from app.core.security import get_password_hash


@pytest.mark.asyncio
async def test_log_audit_creates_entry(db_session):
    """
    Запись аудита с привязкой к user_id.
    Вход: пользователь в БД; log_audit(..., user_id=u.id, action=...).
    Выход: строка в audit_log с тем же user_id и action.
    """
    u = User(username="u1", hashed_password=get_password_hash("testpass12"), is_active=True)
    db_session.add(u)
    await db_session.flush()

    await log_audit(db_session, user_id=u.id, action="test.action")
    await db_session.commit()

    r = await db_session.execute(select(AuditLog).where(AuditLog.action == "test.action"))
    row = r.scalar_one_or_none()
    assert row is not None
    assert row.user_id == u.id


@pytest.mark.asyncio
async def test_log_audit_nullable_fields(db_session):
    """
    Аудит без user_id, ip и details.
    Вход: user_id=None, ip=None, details=None.
    Выход: запись с NULL в этих полях.
    """
    await log_audit(db_session, user_id=None, action="anon.action", ip=None, details=None)
    await db_session.commit()
    r = await db_session.execute(select(AuditLog).where(AuditLog.action == "anon.action"))
    row = r.scalar_one_or_none()
    assert row is not None
    assert row.user_id is None
    assert row.ip is None
    assert row.details is None


@pytest.mark.asyncio
async def test_log_audit_with_details(db_session):
    """
    Аудит с dict в поле details (JSONB).
    Вход: details={"key": "value"}.
    Выход: в БД то же значение dict в колонке details.
    """
    await log_audit(db_session, user_id=None, action="d.action", details={"key": "value"})
    await db_session.commit()
    r = await db_session.execute(select(AuditLog).where(AuditLog.action == "d.action"))
    row = r.scalar_one_or_none()
    assert row.details == {"key": "value"}


@pytest.mark.asyncio
async def test_log_audit_with_resource(db_session):
    """
    Аудит с типом и идентификатором ресурса.
    Вход: resource_type="project", resource_id="42".
    Выход: совпадение в записи audit_log.
    """
    await log_audit(
        db_session,
        user_id=None,
        action="r.action",
        resource_type="project",
        resource_id="42",
    )
    await db_session.commit()
    r = await db_session.execute(select(AuditLog).where(AuditLog.action == "r.action"))
    row = r.scalar_one_or_none()
    assert row.resource_type == "project"
    assert row.resource_id == "42"

"""Unit tests: app.core.security"""
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt as jose_jwt

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.config import get_settings


def test_verify_password_correct():
    """
    verify_password для совпадающего пароля и хеша.
    Вход: Пароль и bcrypt-хеш от того же пароля.
    Выход: True.
    """
    h = get_password_hash("pass")
    assert verify_password("pass", h) is True


def test_verify_password_wrong():
    """
    Неверный пароль.
    Вход: Пароль, отличный от исходного при хешировании.
    Выход: False.
    """
    h = get_password_hash("pass")
    assert verify_password("wrong", h) is False


def test_verify_password_long_truncated():
    """
    Длинная строка пароля: round-trip verify.
    Вход: Строка из 100 символов; хеш от неё же.
    Выход: verify_password с той же строкой возвращает True.
    """
    long_pw = "a" * 100
    h = get_password_hash(long_pw)
    assert verify_password(long_pw, h) is True


def test_verify_password_invalid_hash():
    """
    Некорректная строка хеша (не bcrypt).
    Вход: Произвольная строка вместо хеша.
    Выход: False.
    """
    assert verify_password("pass", "not-a-hash") is False


def test_get_password_hash_roundtrip():
    """
    Хеш не совпадает с паролем; verify успешен.
    Вход: Пароль "secret".
    Выход: Хеш отличается от пароля; verify_password("secret", h) is True.
    """
    h = get_password_hash("secret")
    assert h != "secret"
    assert verify_password("secret", h) is True


def test_create_access_token_contains_sub():
    """
    JWT после create_access_token содержит sub.
    Вход: create_access_token(42).
    Выход: В payload sub == "42" (строка).
    """
    token = create_access_token(42)
    payload = jose_jwt.decode(token, get_settings().secret_key, algorithms=[get_settings().algorithm])
    assert payload["sub"] == "42"


def test_create_access_token_contains_exp():
    """
    JWT содержит exp в будущем.
    Вход: create_access_token(1).
    Выход: Поле exp присутствует; время в будущем относительно UTC "сейчас".
    """
    token = create_access_token(1)
    payload = jose_jwt.decode(token, get_settings().secret_key, algorithms=[get_settings().algorithm])
    assert "exp" in payload
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert exp > datetime.now(timezone.utc)


def test_create_access_token_extra_fields():
    """
    Дополнительные поля в JWT через extra.
    Вход: create_access_token(1, {"role": "admin"}).
    Выход: В декодированном payload есть role.
    """
    token = create_access_token(1, {"role": "admin"})
    payload = jose_jwt.decode(token, get_settings().secret_key, algorithms=[get_settings().algorithm])
    assert payload.get("role") == "admin"


def test_decode_access_token_valid():
    """
    decode_access_token для только что созданного токена.
    Вход: Токен от create_access_token(99).
    Выход: Не None; sub == "99".
    """
    token = create_access_token(99)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "99"


def test_decode_access_token_expired():
    """
    Истёкший JWT.
    Вход: Токен с exp в прошлом (ручной jose.encode).
    Выход: decode_access_token возвращает None.
    """
    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = jose_jwt.encode(
        {"sub": "1", "exp": past},
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    assert decode_access_token(token) is None


def test_decode_access_token_bad_signature():
    """
    Повреждённая подпись JWT.
    Вход: Валидный токен с испорченной третьей частью (после точки).
    Выход: None.
    """
    token = create_access_token(1)
    assert decode_access_token(token) is not None
    parts = token.split(".")
    bad = parts[0] + "." + parts[1] + ".xxx"
    assert decode_access_token(bad) is None


def test_decode_access_token_garbage():
    """
    Строка, не являющаяся JWT.
    Вход: "not.a.jwt".
    Выход: None.
    """
    assert decode_access_token("not.a.jwt") is None

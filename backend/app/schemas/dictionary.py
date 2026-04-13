"""Pydantic schemas for dictionaries (wordlists)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DictionaryResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    filename: str
    size_bytes: int = 0
    word_count: int = 0
    created_at: str | None = None


class DictionaryGenerateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    masks: list[str] = Field(..., min_length=1, description="Hashcat mask patterns, e.g. ['?d?d?d?d?d?d?d?d']")
    description: str | None = None

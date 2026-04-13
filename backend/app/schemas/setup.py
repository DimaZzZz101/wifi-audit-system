"""Getting Started / first-run schemas."""
from pydantic import BaseModel, Field


class SetupStatus(BaseModel):
    setup_completed: bool
    """True if at least one user exists - no need for Getting Started."""


class SetupCreateUser(BaseModel):
    """Create the single initial user (Getting Started)."""
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)

"""Abstract generic repository interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    @abstractmethod
    async def get(self, id: str) -> T | None: ...

    @abstractmethod
    async def list(self, limit: int = 100, offset: int = 0) -> list[T]: ...

    @abstractmethod
    async def save(self, entity: T) -> T: ...

    @abstractmethod
    async def delete(self, id: str) -> bool: ...

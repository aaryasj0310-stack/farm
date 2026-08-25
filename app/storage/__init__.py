"""Storage layer package."""
from app.storage.db import JobStorage, get_storage

__all__ = ["JobStorage", "get_storage"]

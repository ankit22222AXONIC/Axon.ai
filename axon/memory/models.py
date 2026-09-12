"""AXON memory — data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


class MemoryCategory(Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    CONTEXT = "context"
    TASK = "task"


@dataclass
class Memory:
    content: str
    category: MemoryCategory = MemoryCategory.FACT
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        cat = self.category.value if isinstance(self.category, MemoryCategory) else str(self.category)
        return {
            "id": self.id,
            "content": self.content,
            "category": cat,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }

"""AXON memory store — SQLite-backed local persistent memory."""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, List

from axon.memory.models import Memory, MemoryCategory


class MemoryStore:
    def __init__(self, db_path: Optional[str] = None, event_bus=None):
        self.event_bus = event_bus
        self._lock = threading.Lock()
        if db_path is None:
            db_dir = Path.home() / ".axon"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "memory.db")
        else:
            self.db_path = db_path
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self._init_db()

    def _init_db(self):
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        category TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def store(
        self,
        content: str,
        category: Union[str, MemoryCategory] = MemoryCategory.FACT,
    ) -> Memory:
        if not content or not isinstance(content, str) or not content.strip():
            raise ValueError("Memory content cannot be empty")

        cat = category if isinstance(category, MemoryCategory) else self._parse_category(category)
        mem = Memory(content=content.strip(), category=cat)

        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO memories (id, content, category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        mem.id,
                        mem.content,
                        mem.category.value,
                        mem.created_at.isoformat(),
                        mem.updated_at.isoformat(),
                    ),
                )

        if self.event_bus:
            self.event_bus.emit("MEMORY_CREATED", {"id": mem.id, "category": mem.category.value})

        return mem

    def get(self, memory_id: str) -> Optional[Memory]:
        if not memory_id:
            return None
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, content, category, created_at, updated_at FROM memories WHERE id = ?",
                (memory_id,),
            )
            row = cur.fetchone()
        return self._row_to_memory(row) if row else None

    def search(
        self,
        query: str,
        category: Optional[Union[str, MemoryCategory]] = None,
    ) -> List[Memory]:
        if not query or not query.strip():
            return []

        sql = "SELECT id, content, category, created_at, updated_at FROM memories WHERE content LIKE ?"
        params = [f"%{query.strip()}%"]

        if category:
            cat = category if isinstance(category, MemoryCategory) else self._parse_category(category)
            sql += " AND category = ?"
            params.append(cat.value)

        sql += " ORDER BY created_at DESC"
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_memory(row) for row in rows]

    def list(
        self,
        category: Optional[Union[str, MemoryCategory]] = None,
    ) -> List[Memory]:
        sql = "SELECT id, content, category, created_at, updated_at FROM memories"
        params = []

        if category:
            cat = category if isinstance(category, MemoryCategory) else self._parse_category(category)
            sql += " WHERE category = ?"
            params.append(cat.value)

        sql += " ORDER BY created_at DESC"
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_memory(row) for row in rows]

    def forget(self, memory_id: str) -> bool:
        if not memory_id:
            return False
        with self._lock:
            with self._conn:
                cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                deleted = cur.rowcount > 0

        if deleted and self.event_bus:
            self.event_bus.emit("MEMORY_DELETED", {"id": memory_id})
        return deleted

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()

    def _parse_category(self, cat_str: str) -> MemoryCategory:
        try:
            return MemoryCategory(cat_str.lower().strip())
        except (ValueError, AttributeError):
            return MemoryCategory.FACT

    def _row_to_memory(self, row) -> Memory:
        id_, content, category_str, created_at_str, updated_at_str = row
        cat = self._parse_category(category_str)
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except Exception:
            created_at = datetime.now()
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
        except Exception:
            updated_at = datetime.now()
        return Memory(
            id=id_,
            content=content,
            category=cat,
            created_at=created_at,
            updated_at=updated_at,
        )

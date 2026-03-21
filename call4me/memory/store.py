from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

import numpy as np


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    topic TEXT,
                    text TEXT NOT NULL,
                    embedding BLOB,
                    trust REAL DEFAULT 0.8,
                    hit_count INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    source TEXT DEFAULT 'call4me',
                    immutable INTEGER DEFAULT 0,
                    content_hash TEXT,
                    status TEXT DEFAULT 'active'
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_topic ON memories(topic)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(content_hash)")
            conn.commit()

    def upsert(
        self,
        topic: str,
        text: str,
        embedding: np.ndarray,
        trust: float = 0.8,
        source: str = "call4me",
        immutable: bool = False,
    ) -> str:
        content_hash = hashlib.sha256(f"{topic}\n{text}".encode("utf-8")).hexdigest()[:16]
        blob = np.asarray(embedding, dtype=np.float32).tobytes()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, status FROM memories WHERE content_hash = ?", (content_hash,))
            row = cursor.fetchone()
            if row:
                memory_id, status = row
                if status != "active":
                    cursor.execute(
                        """
                        UPDATE memories
                        SET status = 'active', updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (memory_id,),
                    )
                conn.commit()
                return memory_id

            memory_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO memories (
                    id, topic, text, embedding, trust, source, immutable, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    topic,
                    text,
                    blob,
                    trust,
                    source,
                    1 if immutable else 0,
                    content_hash,
                ),
            )
            conn.commit()
            return memory_id

    def get_all_active(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE status = 'active'")
            rows = cursor.fetchall()

        memories: list[dict] = []
        for row in rows:
            item = dict(row)
            item["embedding"] = np.frombuffer(item["embedding"], dtype=np.float32)
            memories.append(item)
        return memories

    def increment_hit(self, memory_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE memories
                SET hit_count = hit_count + 1,
                    last_used_at = datetime('now')
                WHERE id = ?
                """,
                (memory_id,),
            )
            conn.commit()

    def get_recent(self, n: int = 5) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM memories
                WHERE status = 'active'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (n,),
            )
            rows = cursor.fetchall()

        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["embedding"] = np.frombuffer(item["embedding"], dtype=np.float32)
            results.append(item)
        return results

    def deactivate_topic(self, topic: str, keep_id: str | None = None) -> None:
        params: list[str] = [topic]
        query = "UPDATE memories SET status = 'merged' WHERE status = 'active' AND topic = ?"
        if keep_id:
            query += " AND id != ?"
            params.append(keep_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            conn.commit()

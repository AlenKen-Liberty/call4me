from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .embed import MemoryEmbedder
from .seeds import SEED_TIPS
from .store import MemoryStore

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_]+", text.casefold())
    return tokens or text.split()


def _compute_decay(updated_at_str: str, immutable: int) -> float:
    if immutable:
        return 1.0

    try:
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
    except ValueError:
        updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")

    delta = datetime.now(timezone.utc).replace(tzinfo=None) - updated_at.replace(tzinfo=None)
    days = max(delta.total_seconds() / 86400.0, 0)
    return math.exp(-days / 90.0)


@dataclass(slots=True)
class CallMemoryService:
    db_path: str | Path = "data/memory.sqlite"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    store: MemoryStore = field(init=False)
    embedder: MemoryEmbedder = field(init=False)

    def __post_init__(self) -> None:
        self.store = MemoryStore(Path(self.db_path))
        self.embedder = MemoryEmbedder(self.embed_model)
        self._seed_defaults()

    def get_context_for_call(self, company: str, task: str) -> str:
        company_key = self._slug(company)
        task_text = task.strip() or company

        candidates: list[dict] = []
        candidates.extend(self.search(f"ivr {company_key} phone menu", top_k=2))
        candidates.extend(self.search(f"strategy {company_key} {task_text}", top_k=3))
        candidates.extend(self.search(f"outcome {company_key}", top_k=2))
        candidates.extend(self.search(f"general customer service tips {task_text}", top_k=2))

        seen: set[str] = set()
        lines: list[str] = []
        for memory in candidates:
            memory_id = memory["id"]
            if memory_id in seen:
                continue
            seen.add(memory_id)
            lines.append(f"[{memory['topic']}] {memory['text']}")
        return "\n".join(lines)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        memories = self.store.get_all_active()
        if not memories:
            return []

        query_vec = self.embedder.embed(query)
        lexical_scores = self._lexical_scores(memories, query)
        vector_scores = self._vector_scores(memories, query_vec)

        results: list[dict] = []
        for idx, memory in enumerate(memories):
            blended = 0.4 * lexical_scores[idx] + 0.6 * vector_scores[idx]
            trust = float(memory["trust"])
            freq = 1.0 + math.log(1.0 + float(memory["hit_count"]))
            decay = _compute_decay(memory["updated_at"], int(memory["immutable"]))
            weight = blended * trust * freq * decay

            item = {key: value for key, value in memory.items() if key != "embedding"}
            item["weight"] = float(weight)
            item["similarity"] = float(vector_scores[idx])
            results.append(item)

        results.sort(key=lambda item: item["weight"], reverse=True)
        top = results[:top_k]
        for result in top:
            self.store.increment_hit(result["id"])
        return top

    def add(
        self,
        topic: str,
        text: str,
        trust: float = 0.8,
        source: str = "call4me",
        immutable: bool = False,
        replace_topic: bool = False,
    ) -> str:
        embedding = self.embedder.embed(text)
        memory_id = self.store.upsert(
            topic=topic,
            text=text,
            embedding=embedding,
            trust=trust,
            source=source,
            immutable=immutable,
        )
        if replace_topic:
            self.store.deactivate_topic(topic, keep_id=memory_id)
        return memory_id

    def recent(self, n: int = 5) -> list[dict]:
        recent = self.store.get_recent(n)
        for memory in recent:
            memory.pop("embedding", None)
        return recent

    def save_ivr_map(self, company: str, phone: str, path: str, trust: float = 1.0, **metadata: object) -> str:
        topic = f"ivr:{self._slug(company)}"
        lines = [f"Company: {company}", f"Phone: {phone}", f"IVR Path: {path}"]
        for key, value in metadata.items():
            if value in ("", None, [], {}):
                continue
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {value}")
        return self.add(topic=topic, text="\n".join(lines), trust=trust, replace_topic=True)

    def save_strategy(self, company: str, strategy: str, trust: float = 0.9) -> str:
        topic = f"strategy:{self._slug(company)}"
        return self.add(topic=topic, text=strategy.strip(), trust=trust)

    def save_outcome(
        self,
        company: str,
        task: str,
        result: str,
        summary: str,
        duration_sec: int,
        learnings: str = "",
        phone: str = "",
        ivr_path: str = "",
    ) -> str:
        date_str = datetime.now(timezone.utc).date().isoformat()
        lines = [
            f"Company: {company}",
            f"Phone: {phone}" if phone else "",
            f"Task: {task}",
            f"Result: {result}",
            f"Summary: {summary}",
            f"Duration: {max(duration_sec, 0) // 60} min",
            f"IVR Path: {ivr_path}" if ivr_path else "",
            f"Learnings: {learnings}" if learnings else "",
        ]
        text = "\n".join(line for line in lines if line)
        topic = f"outcome:{self._slug(company)}:{date_str}"
        return self.add(topic=topic, text=text, trust=1.0)

    def save_general_tip(self, tip: str, trust: float = 0.8) -> str:
        return self.add(topic="general_tip", text=tip.strip(), trust=trust, immutable=True)

    def _lexical_scores(self, memories: list[dict], query: str) -> np.ndarray:
        corpus_tokens = [_tokenize(memory["text"]) for memory in memories]
        query_tokens = _tokenize(query)

        if BM25Okapi is not None and corpus_tokens:
            bm25 = BM25Okapi(corpus_tokens)
            scores = np.array(bm25.get_scores(query_tokens), dtype=np.float32)
            scores = np.maximum(scores, 0)
            max_score = float(np.max(scores)) if scores.size else 0.0
            return scores / max_score if max_score > 0 else scores

        query_set = set(query_tokens)
        scores = []
        for tokens in corpus_tokens:
            token_set = set(tokens)
            overlap = len(query_set & token_set)
            scores.append(overlap / max(len(query_set), 1))
        return np.asarray(scores, dtype=np.float32)

    def _vector_scores(self, memories: list[dict], query_vec: np.ndarray) -> np.ndarray:
        scores = np.zeros(len(memories), dtype=np.float32)
        query_norm = float(np.linalg.norm(query_vec))
        if query_norm == 0:
            return scores

        for idx, memory in enumerate(memories):
            embedding = memory["embedding"]
            if len(embedding) != len(query_vec):
                continue
            denom = float(np.linalg.norm(embedding) * query_norm)
            if denom == 0:
                continue
            scores[idx] = float(np.dot(embedding, query_vec) / denom)
        return scores

    def _seed_defaults(self) -> None:
        for tip in SEED_TIPS:
            self.save_general_tip(tip)

    @staticmethod
    def _slug(company: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", company.casefold()).strip("_")
        return normalized or "unknown_company"

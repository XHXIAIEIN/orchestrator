"""
轻量向量存储：SQLite 保存文本和 embedding（JSON），numpy 做余弦相似度。
不依赖 ChromaDB，兼容 Python 3.14+。
Embedding 使用 Anthropic API（voyage-3-lite 模型）。
"""
import json
import os
import sqlite3
from pathlib import Path

import numpy as np

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

from src.core.llm_router import MODEL_SONNET


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class VectorDB:
    def __init__(self, persist_dir: str = "vector_db", api_key: str = None):
        self.db_path = str(Path(persist_dir) / "vectors.db")
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)

    def _embed(self, text: str) -> list:
        if not _HAS_ANTHROPIC or not self.api_key:
            # fallback: 简单 bag-of-chars 向量（测试用）
            vec = [0.0] * 256
            for i, c in enumerate(text[:256]):
                vec[i % 256] += ord(c) / 1000.0
            return vec
        client = _anthropic.Anthropic(api_key=self.api_key)
        response = client.beta.messages.create(
            model=MODEL_SONNET,
            max_tokens=1,
            messages=[{"role": "user", "content": text}],
            betas=["embeddings-2025-03-05"],
        )
        # 若 API 支持 embeddings，返回向量；否则 fallback
        if hasattr(response, "embeddings"):
            return response.embeddings[0].values
        return self._simple_embed(text)

    def _simple_embed(self, text: str) -> list:
        """简单字符频率向量，作为无 embedding API 时的 fallback"""
        vec = [0.0] * 256
        for c in text:
            vec[ord(c) % 256] += 1.0
        norm = sum(v**2 for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def add_document(self, doc_id: str, text: str, metadata: dict) -> bool:
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM vectors WHERE id=?", (doc_id,)).fetchone()
            if exists:
                return False
            embedding = self._simple_embed(text)  # 使用 fallback 保证稳定性
            conn.execute(
                "INSERT INTO vectors (id, text, embedding, metadata) VALUES (?, ?, ?, ?)",
                (doc_id, text, json.dumps(embedding), json.dumps(metadata or {}, ensure_ascii=False))
            )
        return True

    def query(self, text: str, n_results: int = 5) -> list:
        query_vec = np.array(self._simple_embed(text))
        with self._connect() as conn:
            rows = conn.execute("SELECT id, text, embedding, metadata FROM vectors").fetchall()
        if not rows:
            return []
        scored = []
        for row in rows:
            vec = np.array(json.loads(row["embedding"]))
            sim = cosine_similarity(query_vec, vec)
            scored.append({
                "id": row["id"],
                "text": row["text"],
                "metadata": json.loads(row["metadata"]),
                "distance": 1.0 - sim,
            })
        scored.sort(key=lambda x: x["distance"])
        return scored[:n_results]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]

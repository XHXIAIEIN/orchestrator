"""
Temporal Knowledge Graph — SQLite triples with time validity.

Stolen from MemPalace R44 P0#4. Tracks facts as (subject, predicate, object)
triples with valid_from/valid_to windows and confidence scores.

Key operations:
    - add_entity / add_triple: insert facts with temporal bounds
    - invalidate: mark a fact as ended (sets valid_to, never deletes)
    - query_entity(as_of=): point-in-time queries
    - timeline: all facts about an entity sorted by time

Uses the same connection pool as EventsDB for consistency.
"""

import json
import logging
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

from src.storage.pool import get_pool

logger = logging.getLogger(__name__)

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "knowledge.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_entities (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    properties  TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kg_ent_name ON kg_entities(name);
CREATE INDEX IF NOT EXISTS idx_kg_ent_type ON kg_entities(entity_type);

CREATE TABLE IF NOT EXISTS kg_triples (
    id            TEXT PRIMARY KEY,
    subject_id    TEXT NOT NULL,
    predicate     TEXT NOT NULL,
    object_id     TEXT NOT NULL,
    valid_from    TEXT,
    valid_to      TEXT,
    confidence    REAL NOT NULL DEFAULT 1.0,
    source        TEXT NOT NULL DEFAULT '',
    extracted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (subject_id) REFERENCES kg_entities(id),
    FOREIGN KEY (object_id)  REFERENCES kg_entities(id)
);
CREATE INDEX IF NOT EXISTS idx_kg_tri_subj ON kg_triples(subject_id);
CREATE INDEX IF NOT EXISTS idx_kg_tri_obj  ON kg_triples(object_id);
CREATE INDEX IF NOT EXISTS idx_kg_tri_pred ON kg_triples(predicate);
CREATE INDEX IF NOT EXISTS idx_kg_tri_valid ON kg_triples(valid_from, valid_to);
"""


# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class KnowledgeGraph:
    """Temporal knowledge graph backed by SQLite."""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._pool = get_pool(db_path, row_factory=sqlite3.Row, log_prefix="kg")
        with self._pool.connect() as conn:
            conn.executescript(_SCHEMA)

    # -- Entity operations ---------------------------------------------------

    def get_or_create_entity(
        self,
        name: str,
        entity_type: str = "unknown",
        properties: dict | None = None,
    ) -> str:
        """Get entity ID by name, or create if not exists. Returns entity ID."""
        with self._pool.connect() as conn:
            row = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (name,)
            ).fetchone()
            if row:
                return row["id"]

            eid = str(uuid.uuid4())[:12]
            props = json.dumps(properties or {}, ensure_ascii=False)
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO kg_entities (id, name, entity_type, properties, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, name, entity_type, props, now, now),
            )
            return eid

    def update_entity(self, name: str, properties: dict) -> None:
        """Merge properties into an existing entity."""
        with self._pool.connect() as conn:
            row = conn.execute(
                "SELECT id, properties FROM kg_entities WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return
            existing = json.loads(row["properties"] or "{}")
            existing.update(properties)
            conn.execute(
                "UPDATE kg_entities SET properties = ?, updated_at = ? WHERE id = ?",
                (json.dumps(existing, ensure_ascii=False), datetime.now().isoformat(), row["id"]),
            )

    # -- Contradiction detection (R44 P1#8) ---------------------------------

    # Predicates that are exclusive (entity can only have one active value)
    EXCLUSIVE_PREDICATES = frozenset({
        "is_a", "type", "role", "status", "owner", "primary_language",
        "runs_on", "deployed_to", "managed_by", "reports_to",
    })

    def check_contradictions(
        self, subject: str, predicate: str, obj: str,
    ) -> list[dict]:
        """Check if a new triple contradicts existing active facts.

        Contradiction types:
            - exclusive_conflict: predicate is exclusive and subject already
              has a different active value (e.g., "X is_a tool" vs "X is_a project")
            - temporal_overlap: same triple was invalidated recently (might be stale)

        Returns list of contradictions (empty = no conflicts).
        """
        contradictions = []
        with self._pool.connect() as conn:
            sub_row = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (subject,)
            ).fetchone()
            if not sub_row:
                return []

            sub_id = sub_row["id"]

            # Check exclusive predicates
            if predicate in self.EXCLUSIVE_PREDICATES:
                existing = conn.execute(
                    "SELECT t.id, e.name AS object_name, t.confidence "
                    "FROM kg_triples t JOIN kg_entities e ON t.object_id = e.id "
                    "WHERE t.subject_id = ? AND t.predicate = ? AND t.valid_to IS NULL",
                    (sub_id, predicate),
                ).fetchall()

                for row in existing:
                    if row["object_name"] != obj:
                        contradictions.append({
                            "type": "exclusive_conflict",
                            "subject": subject,
                            "predicate": predicate,
                            "existing_value": row["object_name"],
                            "new_value": obj,
                            "existing_confidence": row["confidence"],
                        })

            # Check recently invalidated (potential stale re-assertion)
            obj_row = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (obj,)
            ).fetchone()
            if obj_row:
                recently_ended = conn.execute(
                    "SELECT valid_to FROM kg_triples "
                    "WHERE subject_id = ? AND predicate = ? AND object_id = ? "
                    "AND valid_to IS NOT NULL "
                    "ORDER BY valid_to DESC LIMIT 1",
                    (sub_id, predicate, obj_row["id"]),
                ).fetchone()
                if recently_ended:
                    contradictions.append({
                        "type": "temporal_overlap",
                        "subject": subject,
                        "predicate": predicate,
                        "object": obj,
                        "previously_ended": recently_ended["valid_to"],
                        "note": "This fact was previously invalidated. Re-adding may indicate a reversal or error.",
                    })

        return contradictions

    # -- Triple operations ---------------------------------------------------

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        subject_type: str = "unknown",
        object_type: str = "unknown",
        valid_from: str | None = None,
        confidence: float = 1.0,
        source: str = "",
        check_conflicts: bool = True,
    ) -> str:
        """Add a fact triple. Auto-creates entities if needed. Returns triple ID.

        When check_conflicts=True (default), logs warnings for contradictions
        but still adds the triple. Callers can check_contradictions() first
        for stricter validation.
        """
        if check_conflicts:
            conflicts = self.check_contradictions(subject, predicate, obj)
            for c in conflicts:
                if c["type"] == "exclusive_conflict":
                    logger.warning(
                        "KG contradiction: %s --%s--> %s conflicts with existing --%s--> %s",
                        subject, predicate, obj, predicate, c["existing_value"],
                    )
                elif c["type"] == "temporal_overlap":
                    logger.info(
                        "KG re-assertion: %s --%s--> %s was previously ended at %s",
                        subject, predicate, obj, c["previously_ended"],
                    )

        sub_id = self.get_or_create_entity(subject, subject_type)
        obj_id = self.get_or_create_entity(obj, object_type)
        tid = str(uuid.uuid4())[:12]
        vf = valid_from or date.today().isoformat()

        with self._pool.connect() as conn:
            # Check for existing active triple (same subject+predicate+object, no valid_to)
            existing = conn.execute(
                "SELECT id FROM kg_triples "
                "WHERE subject_id = ? AND predicate = ? AND object_id = ? AND valid_to IS NULL",
                (sub_id, predicate, obj_id),
            ).fetchone()
            if existing:
                # Already active — update confidence if higher
                conn.execute(
                    "UPDATE kg_triples SET confidence = MAX(confidence, ?), source = ? WHERE id = ?",
                    (confidence, source, existing["id"]),
                )
                return existing["id"]

            conn.execute(
                "INSERT INTO kg_triples "
                "(id, subject_id, predicate, object_id, valid_from, confidence, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tid, sub_id, predicate, obj_id, vf, confidence, source),
            )
            return tid

    def invalidate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        ended: str | None = None,
    ) -> int:
        """Mark a fact as ended (sets valid_to). Never deletes. Returns rows affected."""
        ended = ended or date.today().isoformat()
        with self._pool.connect() as conn:
            sub_row = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (subject,)
            ).fetchone()
            obj_row = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (obj,)
            ).fetchone()
            if not sub_row or not obj_row:
                return 0
            cursor = conn.execute(
                "UPDATE kg_triples SET valid_to = ? "
                "WHERE subject_id = ? AND predicate = ? AND object_id = ? AND valid_to IS NULL",
                (ended, sub_row["id"], predicate, obj_row["id"]),
            )
            return cursor.rowcount

    # -- Query operations ----------------------------------------------------

    def query_entity(
        self,
        name: str,
        as_of: str | None = None,
        direction: str = "both",
    ) -> list[dict]:
        """Query all facts about an entity, optionally at a point in time.

        direction: 'outgoing' (entity as subject), 'incoming' (entity as object), 'both'
        as_of: ISO date string for point-in-time query (default: current facts only)
        """
        with self._pool.connect() as conn:
            ent = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (name,)
            ).fetchone()
            if not ent:
                return []

            eid = ent["id"]
            results = []

            if direction in ("outgoing", "both"):
                query = (
                    "SELECT t.*, e.name AS object_name, e.entity_type AS object_type "
                    "FROM kg_triples t JOIN kg_entities e ON t.object_id = e.id "
                    "WHERE t.subject_id = ?"
                )
                params: list = [eid]
                if as_of:
                    query += " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                    query += " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                    params.extend([as_of, as_of])
                else:
                    # Current facts only (valid_to IS NULL)
                    query += " AND t.valid_to IS NULL"

                for row in conn.execute(query, params).fetchall():
                    results.append({
                        "direction": "outgoing",
                        "subject": name,
                        "predicate": row["predicate"],
                        "object": row["object_name"],
                        "object_type": row["object_type"],
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "confidence": row["confidence"],
                        "source": row["source"],
                    })

            if direction in ("incoming", "both"):
                query = (
                    "SELECT t.*, e.name AS subject_name, e.entity_type AS subject_type "
                    "FROM kg_triples t JOIN kg_entities e ON t.subject_id = e.id "
                    "WHERE t.object_id = ?"
                )
                params = [eid]
                if as_of:
                    query += " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                    query += " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                    params.extend([as_of, as_of])
                else:
                    query += " AND t.valid_to IS NULL"

                for row in conn.execute(query, params).fetchall():
                    results.append({
                        "direction": "incoming",
                        "subject": row["subject_name"],
                        "subject_type": row["subject_type"],
                        "predicate": row["predicate"],
                        "object": name,
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "confidence": row["confidence"],
                        "source": row["source"],
                    })

            return results

    def timeline(self, name: str) -> list[dict]:
        """All facts about an entity, sorted by valid_from. Includes expired facts."""
        with self._pool.connect() as conn:
            ent = conn.execute(
                "SELECT id FROM kg_entities WHERE name = ?", (name,)
            ).fetchone()
            if not ent:
                return []

            eid = ent["id"]
            rows = conn.execute(
                "SELECT t.*, "
                "  s.name AS subject_name, s.entity_type AS subject_type, "
                "  o.name AS object_name, o.entity_type AS object_type "
                "FROM kg_triples t "
                "JOIN kg_entities s ON t.subject_id = s.id "
                "JOIN kg_entities o ON t.object_id = o.id "
                "WHERE t.subject_id = ? OR t.object_id = ? "
                "ORDER BY t.valid_from ASC NULLS FIRST",
                (eid, eid),
            ).fetchall()

            return [
                {
                    "subject": r["subject_name"],
                    "predicate": r["predicate"],
                    "object": r["object_name"],
                    "valid_from": r["valid_from"],
                    "valid_to": r["valid_to"],
                    "confidence": r["confidence"],
                    "active": r["valid_to"] is None,
                }
                for r in rows
            ]

    # -- Entity detection (R44 P1#10) ---------------------------------------

    @staticmethod
    def detect_entity_type(name: str, context: str = "") -> str:
        """Multi-signal classification: person vs project vs tool vs unknown.

        Signal weights (from MemPalace):
            - Direct address markers (4x): @, 他/她, you, 主人
            - Action verbs (2x): said, asked, wrote, committed
            - Pronoun proximity (2x): he/she/they near the name
            - Conversation markers (3x): name appears after > or Q:
            - Project indicators (3x): repo, package, module, src/, .py, .js
            - Tool indicators (2x): cli, sdk, api, server, database

        Requires >= 2 different signal categories to confirm as person.
        """
        text = f"{name} {context}".lower()
        scores = {"person": 0, "project": 0, "tool": 0}
        signal_categories: dict[str, set[str]] = {"person": set(), "project": set(), "tool": set()}

        # Person signals
        person_direct = ["@", "他说", "她说", "他的", "她的", "你说", "主人",
                         "said", "asked", "told", "wrote"]
        person_pronouns = ["he ", "she ", "they ", "他 ", "她 ", "我 "]
        person_convo = [f"> {name.lower()}", f"> **{name.lower()}", f"{name.lower()}:"]
        person_verbs = ["committed", "pushed", "reviewed", "approved", "requested"]

        for p in person_direct:
            if p in text:
                scores["person"] += 4
                signal_categories["person"].add("direct")
        for p in person_verbs:
            if p in text:
                scores["person"] += 2
                signal_categories["person"].add("verb")
        for p in person_pronouns:
            if p in text:
                scores["person"] += 2
                signal_categories["person"].add("pronoun")
        for p in person_convo:
            if p in text:
                scores["person"] += 3
                signal_categories["person"].add("conversation")

        # Project signals
        project_markers = ["repo", "repository", "package", "module", "仓库",
                           "src/", ".py", ".js", ".ts", "github.com",
                           "docker", "compose", "deploy"]
        for p in project_markers:
            if p in text:
                scores["project"] += 3
                signal_categories["project"].add("marker")

        # Tool signals
        tool_markers = ["cli", "sdk", "api", "server", "database", "client",
                        "ollama", "qdrant", "sqlite", "chromadb", "redis"]
        for p in tool_markers:
            if p in text:
                scores["tool"] += 2
                signal_categories["tool"].add("marker")

        # Person requires >= 2 different signal categories
        if scores["person"] > 0 and len(signal_categories["person"]) < 2:
            scores["person"] = scores["person"] // 2  # downgrade

        # Pick highest score
        if max(scores.values()) == 0:
            return "unknown"
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    # -- Stats ---------------------------------------------------------------

    def stats(self) -> dict:
        """Return basic graph statistics."""
        with self._pool.connect() as conn:
            entities = conn.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
            triples = conn.execute("SELECT COUNT(*) FROM kg_triples").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM kg_triples WHERE valid_to IS NULL"
            ).fetchone()[0]
            return {"entities": entities, "triples": triples, "active_triples": active}

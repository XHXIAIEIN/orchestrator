"""Ontology Graph — Cross-department knowledge graph on SQLite.

Provides typed Entity-Relation graph for Orchestrator. Entities represent
projects, departments, steal patterns, skills, learnings, and artifacts.
Relations capture cross-department dependencies and knowledge flow.

Based on R23 steal (oswalpalash/ontology), adapted: SQLite instead of JSONL,
6 Orchestrator-specific entity types, BFS traversal in Python.
"""

import hashlib
import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.storage.pool import get_pool

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not (
    (_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()
):
    _REPO_ROOT = _REPO_ROOT.parent

_DEFAULT_DB = str(_REPO_ROOT / "data" / "events.db")

# ── Constants ──────────────────────────────────────────────────────────

ENTITY_TYPES = frozenset({
    "project", "department", "steal_pattern", "skill", "learning", "artifact",
})

RELATION_TYPES = frozenset({
    "owns", "produces", "depends_on", "implements", "affects", "references",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id(entity_type: str, name: str) -> str:
    """Generate a deterministic entity ID from type + name."""
    prefix_map = {
        "project": "proj",
        "department": "dept",
        "steal_pattern": "steal",
        "skill": "skill",
        "learning": "learn",
        "artifact": "art",
    }
    prefix = prefix_map.get(entity_type, entity_type[:4])
    slug = name.lower().replace(" ", "_").replace("/", "_")[:60]
    return f"{prefix}:{slug}"


# ── OntologyGraph ──────────────────────────────────────────────────────

class OntologyGraph:
    """Cross-department knowledge graph backed by SQLite.

    Uses the same events.db via the shared SQLitePool singleton.
    Tables are created by _schema.py DDL on EventsDB init.
    """

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._pool = get_pool(
            db_path,
            row_factory=sqlite3.Row,
            log_prefix="ontology",
        )
        self._ensure_tables()

    def _connect(self):
        return self._pool.connect()

    def _ensure_tables(self):
        """Create ontology tables if they don't exist (idempotent)."""
        ddl = """
        CREATE TABLE IF NOT EXISTS ontology_entities (
            id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, name TEXT NOT NULL,
            properties TEXT NOT NULL DEFAULT '{}', source_table TEXT,
            source_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ontology_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT NOT NULL,
            relation_type TEXT NOT NULL, to_id TEXT NOT NULL,
            properties TEXT NOT NULL DEFAULT '{}', weight REAL DEFAULT 1.0,
            created_at TEXT NOT NULL, UNIQUE(from_id, relation_type, to_id)
        );
        CREATE TABLE IF NOT EXISTS ontology_ops (
            id INTEGER PRIMARY KEY AUTOINCREMENT, op TEXT NOT NULL,
            entity_id TEXT, relation_id INTEGER,
            data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ontology_type_schema (
            entity_type TEXT PRIMARY KEY, constraints TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
        try:
            with self._connect() as conn:
                conn.executescript(ddl)
        except Exception as exc:
            log.warning("ontology: table init skipped: %s", exc)

    # ── Entity CRUD ────────────────────────────────────────────────────

    def add_entity(
        self,
        entity_type: str,
        name: str,
        properties: dict[str, Any] | None = None,
        source: tuple[str, int] | None = None,
        entity_id: str | None = None,
    ) -> str:
        """Create an entity. Returns the entity ID.

        Args:
            entity_type: One of ENTITY_TYPES.
            name: Human-readable name.
            properties: Type-specific JSON properties.
            source: Optional (table_name, row_id) back-link.
            entity_id: Override auto-generated ID.
        """
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unknown entity type: {entity_type}. Must be one of {ENTITY_TYPES}")

        props = properties or {}
        errors = self.validate(entity_type, props)
        if errors:
            raise ValueError(f"Constraint violations: {errors}")

        eid = entity_id or _make_id(entity_type, name)
        now = _now()
        src_table, src_id = source if source else (None, None)

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO ontology_entities
                   (id, entity_type, name, properties, source_table, source_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, properties=excluded.properties,
                     source_table=excluded.source_table, source_id=excluded.source_id,
                     updated_at=excluded.updated_at""",
                (eid, entity_type, name, json.dumps(props, ensure_ascii=False),
                 src_table, src_id, now, now),
            )
            self._log_op(conn, "create", entity_id=eid, data={"type": entity_type, "name": name})

        return eid

    def get(self, entity_id: str) -> dict | None:
        """Fetch a single entity by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ontology_entities WHERE id = ?", (entity_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def update_entity(self, entity_id: str, properties: dict[str, Any]) -> bool:
        """Merge properties into an existing entity. Returns True if found."""
        existing = self.get(entity_id)
        if not existing:
            return False

        merged = {**existing["properties"], **properties}
        errors = self.validate(existing["entity_type"], merged)
        if errors:
            raise ValueError(f"Constraint violations: {errors}")

        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE ontology_entities SET properties = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), now, entity_id),
            )
            self._log_op(conn, "update", entity_id=entity_id, data={"merged": properties})
        return True

    def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and all its relations. Returns True if found."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM ontology_entities WHERE id = ?", (entity_id,))
            if cur.rowcount == 0:
                return False
            conn.execute(
                "DELETE FROM ontology_relations WHERE from_id = ? OR to_id = ?",
                (entity_id, entity_id),
            )
            self._log_op(conn, "delete", entity_id=entity_id)
        return True

    # ── Relations ──────────────────────────────────────────────────────

    def relate(
        self,
        from_id: str,
        rel_type: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
        weight: float = 1.0,
    ) -> int:
        """Create a relation between two entities. Returns the relation ID.

        Raises ValueError if either entity doesn't exist or rel_type is unknown.
        """
        if rel_type not in RELATION_TYPES:
            raise ValueError(f"Unknown relation type: {rel_type}. Must be one of {RELATION_TYPES}")

        with self._connect() as conn:
            # Verify both entities exist
            for eid in (from_id, to_id):
                if not conn.execute("SELECT 1 FROM ontology_entities WHERE id = ?", (eid,)).fetchone():
                    raise ValueError(f"Entity not found: {eid}")

            now = _now()
            props = json.dumps(properties or {}, ensure_ascii=False)
            cur = conn.execute(
                """INSERT INTO ontology_relations
                   (from_id, relation_type, to_id, properties, weight, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(from_id, relation_type, to_id) DO UPDATE SET
                     properties=excluded.properties, weight=excluded.weight""",
                (from_id, rel_type, to_id, props, weight, now),
            )
            rid = cur.lastrowid
            self._log_op(conn, "relate", data={
                "from": from_id, "type": rel_type, "to": to_id,
            }, relation_id=rid)
        return rid

    def unrelate(self, from_id: str, rel_type: str, to_id: str) -> bool:
        """Remove a specific relation. Returns True if it existed."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM ontology_relations WHERE from_id=? AND relation_type=? AND to_id=?",
                (from_id, rel_type, to_id),
            )
            if cur.rowcount > 0:
                self._log_op(conn, "unrelate", data={
                    "from": from_id, "type": rel_type, "to": to_id,
                })
            return cur.rowcount > 0

    # ── Queries ────────────────────────────────────────────────────────

    def query(
        self,
        entity_type: str | None = None,
        name_like: str | None = None,
        **property_filters,
    ) -> list[dict]:
        """Query entities by type and/or property filters.

        Property filters use JSON extract: ``status="active"`` checks
        ``json_extract(properties, '$.status') = 'active'``.
        """
        clauses = []
        params: list[Any] = []

        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if name_like:
            clauses.append("name LIKE ?")
            params.append(f"%{name_like}%")
        for key, val in property_filters.items():
            clauses.append(f"json_extract(properties, '$.{key}') = ?")
            params.append(val)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM ontology_entities {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def neighbors(
        self,
        entity_id: str,
        rel_type: str | None = None,
        direction: str = "out",
    ) -> list[dict]:
        """Get neighboring entities via relations.

        Args:
            direction: "out" (from this entity), "in" (to this entity), "both".
        """
        results = []
        with self._connect() as conn:
            if direction in ("out", "both"):
                clause = "r.from_id = ?"
                if rel_type:
                    clause += " AND r.relation_type = ?"
                sql = f"""
                    SELECT e.*, r.relation_type, r.weight, r.properties as rel_props
                    FROM ontology_relations r
                    JOIN ontology_entities e ON e.id = r.to_id
                    WHERE {clause}
                """
                params = [entity_id] + ([rel_type] if rel_type else [])
                results.extend(conn.execute(sql, params).fetchall())

            if direction in ("in", "both"):
                clause = "r.to_id = ?"
                if rel_type:
                    clause += " AND r.relation_type = ?"
                sql = f"""
                    SELECT e.*, r.relation_type, r.weight, r.properties as rel_props
                    FROM ontology_relations r
                    JOIN ontology_entities e ON e.id = r.from_id
                    WHERE {clause}
                """
                params = [entity_id] + ([rel_type] if rel_type else [])
                results.extend(conn.execute(sql, params).fetchall())

        return [self._row_to_dict(r, include_rel=True) for r in results]

    def traverse(
        self,
        start_id: str,
        rel_types: list[str] | None = None,
        max_depth: int = 3,
        direction: str = "out",
    ) -> dict[str, int]:
        """BFS traversal from start_id. Returns {entity_id: depth}.

        Args:
            rel_types: Filter to specific relation types (None = all).
            max_depth: Maximum traversal depth.
            direction: "out", "in", or "both".
        """
        visited: dict[str, int] = {}
        queue: list[tuple[str, int]] = [(start_id, 0)]

        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited[current] = depth

            if depth < max_depth:
                for nb in self.neighbors(current, direction=direction):
                    nid = nb["id"]
                    if rel_types and nb.get("relation_type") not in rel_types:
                        continue
                    if nid not in visited:
                        queue.append((nid, depth + 1))

        visited.pop(start_id, None)
        return visited

    # ── Cross-Department ───────────────────────────────────────────────

    def cross_department(self, dept_a: str, dept_b: str) -> list[dict]:
        """Find entities shared between two departments via any relation.

        Returns entities that both departments connect to (directly).
        """
        dept_a_id = f"dept:{dept_a}" if not dept_a.startswith("dept:") else dept_a
        dept_b_id = f"dept:{dept_b}" if not dept_b.startswith("dept:") else dept_b

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT e.*
                FROM ontology_entities e
                WHERE e.id IN (
                    SELECT to_id FROM ontology_relations WHERE from_id = ?
                    UNION
                    SELECT from_id FROM ontology_relations WHERE to_id = ?
                )
                AND e.id IN (
                    SELECT to_id FROM ontology_relations WHERE from_id = ?
                    UNION
                    SELECT from_id FROM ontology_relations WHERE to_id = ?
                )
                """,
                (dept_a_id, dept_a_id, dept_b_id, dept_b_id),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def department_knowledge(self, dept_key: str) -> dict:
        """Build a knowledge summary for a single department.

        Returns:
            {
                "department": dept_key,
                "entities": [...],      # all entities this dept relates to
                "relations": [...],     # all relations involving this dept
                "stats": {entity_type: count},
            }
        """
        dept_id = f"dept:{dept_key}" if not dept_key.startswith("dept:") else dept_key
        entities = self.neighbors(dept_id, direction="both")
        stats: dict[str, int] = defaultdict(int)
        for e in entities:
            stats[e["entity_type"]] += 1

        with self._connect() as conn:
            relations = conn.execute(
                """SELECT * FROM ontology_relations
                   WHERE from_id = ? OR to_id = ?""",
                (dept_id, dept_id),
            ).fetchall()

        return {
            "department": dept_key,
            "entities": entities,
            "relations": [dict(r) for r in relations],
            "stats": dict(stats),
        }

    # ── Type Constraints ───────────────────────────────────────────────

    def set_schema(self, entity_type: str, constraints: dict) -> None:
        """Set or update type constraints for an entity type.

        Constraints format:
            {
                "required": ["field1", "field2"],
                "enums": {"status": ["active", "archived", "planned"]},
                "forbidden": ["password", "secret", "token"],
            }
        """
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO ontology_type_schema (entity_type, constraints, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(entity_type) DO UPDATE SET
                     constraints=excluded.constraints, updated_at=excluded.updated_at""",
                (entity_type, json.dumps(constraints, ensure_ascii=False), now),
            )

    def validate(self, entity_type: str, properties: dict) -> list[str]:
        """Validate properties against type schema. Returns list of violations."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT constraints FROM ontology_type_schema WHERE entity_type = ?",
                (entity_type,),
            ).fetchone()

        if not row:
            return []

        constraints = json.loads(row["constraints"])
        errors: list[str] = []

        for req in constraints.get("required", []):
            if req not in properties or properties[req] is None:
                errors.append(f"Missing required property: {req}")

        for field, allowed in constraints.get("enums", {}).items():
            if field in properties and properties[field] not in allowed:
                errors.append(f"Invalid value for {field}: {properties[field]}. Must be one of {allowed}")

        for forbidden in constraints.get("forbidden", []):
            if forbidden in properties:
                errors.append(f"Forbidden property: {forbidden}")

        return errors

    # ── Stats ──────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return graph statistics."""
        with self._connect() as conn:
            entity_count = conn.execute("SELECT COUNT(*) FROM ontology_entities").fetchone()[0]
            relation_count = conn.execute("SELECT COUNT(*) FROM ontology_relations").fetchone()[0]
            type_counts = conn.execute(
                "SELECT entity_type, COUNT(*) as cnt FROM ontology_entities GROUP BY entity_type"
            ).fetchall()
            rel_type_counts = conn.execute(
                "SELECT relation_type, COUNT(*) as cnt FROM ontology_relations GROUP BY relation_type"
            ).fetchall()
        return {
            "entities": entity_count,
            "relations": relation_count,
            "by_type": {r["entity_type"]: r["cnt"] for r in type_counts},
            "by_relation": {r["relation_type"]: r["cnt"] for r in rel_type_counts},
        }

    # ── Seed ───────────────────────────────────────────────────────────

    def seed_departments(self) -> list[str]:
        """Seed department entities from manifest.yaml files. Returns created IDs."""
        import yaml

        dept_dir = _REPO_ROOT / "departments"
        if not dept_dir.is_dir():
            return []

        created = []
        for manifest_path in sorted(dept_dir.glob("*/manifest.yaml")):
            try:
                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("ontology: failed to read %s: %s", manifest_path, exc)
                continue

            key = data.get("key", manifest_path.parent.name)
            eid = self.add_entity(
                entity_type="department",
                name=data.get("name_zh", key),
                properties={
                    "key": key,
                    "name_zh": data.get("name_zh", ""),
                    "description": data.get("description", ""),
                    "authority": data.get("authority", "READ"),
                    "model": data.get("model", ""),
                    "tags": data.get("tags", []),
                    "divisions": list(data.get("divisions", {}).keys()),
                },
                entity_id=f"dept:{key}",
            )
            created.append(eid)

            # Seed division entities as skills owned by the department
            for div_key, div_data in data.get("divisions", {}).items():
                sid = self.add_entity(
                    entity_type="skill",
                    name=div_data.get("name_zh", div_key),
                    properties={
                        "department": key,
                        "division": div_key,
                        "description": div_data.get("description", ""),
                        "exam_dimension": div_data.get("exam_dimension", ""),
                    },
                    entity_id=f"skill:{key}/{div_key}",
                )
                created.append(sid)
                try:
                    self.relate(eid, "owns", sid)
                except ValueError:
                    pass  # already exists

        return created

    def seed_default_schemas(self) -> None:
        """Register default type constraints for all entity types."""
        schemas = {
            "project": {
                "required": ["status"],
                "enums": {"status": ["active", "archived", "planned", "paused"]},
                "forbidden": ["password", "secret", "token", "api_key"],
            },
            "department": {
                "required": ["key"],
                "enums": {"authority": ["READ", "MUTATE", "ADMIN"]},
                "forbidden": ["password", "secret", "token", "api_key"],
            },
            "steal_pattern": {
                "required": ["round", "priority"],
                "enums": {
                    "priority": ["P0", "P1", "P2"],
                    "status": ["pending", "implemented", "adapted", "skipped"],
                },
                "forbidden": [],
            },
            "skill": {
                "required": ["department"],
                "forbidden": ["password", "secret", "token", "api_key"],
            },
            "learning": {
                "required": ["rule", "area"],
                "forbidden": ["password", "secret", "token", "api_key"],
            },
            "artifact": {
                "required": ["path"],
                "enums": {"artifact_type": ["file", "design", "report", "config", "script"]},
                "forbidden": ["password", "secret", "token", "api_key"],
            },
        }
        for etype, constraints in schemas.items():
            self.set_schema(etype, constraints)

    # ── Internals ──────────────────────────────────────────────────────

    def _log_op(
        self,
        conn: sqlite3.Connection,
        op: str,
        entity_id: str | None = None,
        relation_id: int | None = None,
        data: dict | None = None,
    ):
        """Append to ontology_ops log."""
        conn.execute(
            "INSERT INTO ontology_ops (op, entity_id, relation_id, data, created_at) VALUES (?,?,?,?,?)",
            (op, entity_id, relation_id, json.dumps(data or {}, ensure_ascii=False), _now()),
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, include_rel: bool = False) -> dict:
        """Convert a sqlite3.Row to a dict, parsing JSON fields."""
        d = dict(row)
        for json_field in ("properties", "rel_props"):
            if json_field in d and isinstance(d[json_field], str):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        if not include_rel:
            d.pop("relation_type", None)
            d.pop("weight", None)
            d.pop("rel_props", None)
        return d

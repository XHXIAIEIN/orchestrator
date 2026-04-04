# Ontology Graph — Cross-Department Knowledge Graph

**Date**: 2026-04-04
**Status**: Approved
**Source**: R23 steal (oswalpalash/ontology v1.0.4), adapted for Orchestrator

## Problem

Orchestrator's knowledge is fragmented:
- Structured memory (6-dim tuples) has no inter-entity relationships
- Department outputs (run_logs) are isolated silos — no cross-department linkage
- Steal patterns, learnings, and artifacts have implicit relationships that require grep to discover
- `knowledge_graph.py` only does code dependency blast radius, not semantic knowledge

## Solution

Add an Entity-Relation graph layer to events.db. Four new tables, six entity types, six relation types. Python API for CRUD + traversal + cross-department queries.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  OntologyGraph                   │
│          src/governance/ontology.py              │
├─────────────────────────────────────────────────┤
│  add_entity()  relate()  traverse()             │
│  query()       neighbors()  cross_department()  │
│  validate()    department_knowledge()            │
├─────────────────────────────────────────────────┤
│            events.db (4 new tables)              │
│  ontology_entities  ontology_relations           │
│  ontology_ops       ontology_type_schema         │
└─────────────────────────────────────────────────┘
         ↕ source_table/source_id links
┌─────────────────────────────────────────────────┐
│  Existing tables: learnings, run_logs, tasks,   │
│  events, experiences, file_index                 │
└─────────────────────────────────────────────────┘
```

## DB Schema

### Table 1: `ontology_entities` — Graph Nodes

```sql
CREATE TABLE IF NOT EXISTS ontology_entities (
    id          TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    name        TEXT NOT NULL,
    properties  TEXT NOT NULL DEFAULT '{}',
    source_table TEXT,
    source_id   INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_onto_ent_type ON ontology_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_onto_ent_source ON ontology_entities(source_table, source_id);
```

- `id`: Human-readable slug — `"dept:engineering"`, `"steal:r23_ontology"`, `"learning:42"`
- `entity_type`: One of 6 types (see below)
- `properties`: JSON, type-specific attributes
- `source_table`/`source_id`: Optional back-link to existing table row

### Table 2: `ontology_relations` — Graph Edges

```sql
CREATE TABLE IF NOT EXISTS ontology_relations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id       TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    to_id         TEXT NOT NULL,
    properties    TEXT NOT NULL DEFAULT '{}',
    weight        REAL DEFAULT 1.0,
    created_at    TEXT NOT NULL,
    UNIQUE(from_id, relation_type, to_id)
);
CREATE INDEX IF NOT EXISTS idx_onto_rel_from ON ontology_relations(from_id);
CREATE INDEX IF NOT EXISTS idx_onto_rel_to ON ontology_relations(to_id);
CREATE INDEX IF NOT EXISTS idx_onto_rel_type ON ontology_relations(relation_type);
```

- Unique constraint prevents duplicate edges
- `weight`: Relation strength, useful for ranking/decay
- Bidirectional indexing (from + to) for both forward and reverse traversal

### Table 3: `ontology_ops` — Append-Only Change Log

```sql
CREATE TABLE IF NOT EXISTS ontology_ops (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    op         TEXT NOT NULL,
    entity_id  TEXT,
    relation_id INTEGER,
    data       TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_onto_ops_entity ON ontology_ops(entity_id);
```

- Every mutation (create/update/delete/relate/unrelate) logged here
- Enables full change history and audit trail

### Table 4: `ontology_type_schema` — Type Constraints

```sql
CREATE TABLE IF NOT EXISTS ontology_type_schema (
    entity_type TEXT PRIMARY KEY,
    constraints TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

- JSON constraints: `{required: [...], enums: {field: [values]}, forbidden: [...]}`
- Validated before entity creation/update

## Entity Types (6)

| Type | ID Pattern | Required Properties | Source |
|------|-----------|-------------------|--------|
| `project` | `proj:<slug>` | `status`, `path` | Manual |
| `department` | `dept:<key>` | `name_zh`, `authority` | manifest.yaml |
| `steal_pattern` | `steal:<round>_<slug>` | `round`, `priority`, `status` | Steal docs |
| `skill` | `skill:<dept>/<name>` | `department`, `skill_path` | SKILL.md |
| `learning` | `learn:<id>` | `rule`, `area` | learnings table |
| `artifact` | `art:<path_hash>` | `path`, `artifact_type` | run_logs |

## Relation Types (6)

| Relation | From → To | Semantics |
|----------|----------|-----------|
| `owns` | department → artifact/skill | Department is responsible for entity |
| `produces` | department/task → artifact | Run produced this output |
| `depends_on` | entity → entity | Requires another entity |
| `implements` | artifact → steal_pattern | Code realizes a stolen pattern |
| `affects` | artifact → department | Changes here impact that department |
| `references` | entity → entity | Generic cross-reference |

## Python API

File: `src/governance/ontology.py`

```python
class OntologyGraph:
    def __init__(self, db_path: str | None = None)

    # ── Entity CRUD ──
    def add_entity(self, entity_type: str, name: str,
                   properties: dict = None, source: tuple[str, int] = None) -> str
    def get(self, entity_id: str) -> dict | None
    def update_entity(self, entity_id: str, properties: dict) -> bool
    def remove_entity(self, entity_id: str) -> bool

    # ── Relations ──
    def relate(self, from_id: str, rel_type: str, to_id: str,
               properties: dict = None, weight: float = 1.0) -> int
    def unrelate(self, from_id: str, rel_type: str, to_id: str) -> bool

    # ── Queries ──
    def query(self, entity_type: str = None, **property_filters) -> list[dict]
    def neighbors(self, entity_id: str, rel_type: str = None,
                  direction: str = "out") -> list[dict]
    def traverse(self, start_id: str, rel_types: list[str] = None,
                 max_depth: int = 3) -> dict  # BFS, returns {id: depth}

    # ── Cross-Department ──
    def cross_department(self, dept_a: str, dept_b: str) -> list[dict]
    def department_knowledge(self, dept_key: str) -> dict

    # ── Constraints ──
    def set_schema(self, entity_type: str, constraints: dict) -> None
    def validate(self, entity_type: str, properties: dict) -> list[str]
```

## Integration Points

1. **_schema.py**: Add DDL + migrations for 4 new tables
2. **run_logs hook**: After department run completes, auto-register artifact entities + `produces` relation
3. **learnings mixin**: When learning is created/promoted, sync to ontology entity
4. **dispatcher.py**: Query graph for cross-department dependencies before dispatch (advisory, not blocking)

## What This Does NOT Do

- Does not replace structured_memory.py (coexists — graph is relations, memory is content)
- Does not replace knowledge_graph.py (that's code dependency, this is semantic)
- Does not enforce skill contracts yet (future Phase 3 from R23)
- Does not use JSONL (SQLite is superior for this scale)

## Success Criteria

- `OntologyGraph` can CRUD entities and relations
- BFS traversal returns correct subgraph within max_depth
- `cross_department()` finds shared entities between any two departments
- Type constraints reject invalid entities
- All mutations logged to ontology_ops

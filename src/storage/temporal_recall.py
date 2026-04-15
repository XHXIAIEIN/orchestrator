"""R64 Hindsight: Two-Phase Temporal Recall — date-first, then embedding.

Problem: Searching events by semantic similarity over the full table
is O(N) in embedding distance computation. For a 50K+ events table,
this is prohibitively slow.

Solution (Hindsight's approach):
    Phase 1: Use date index to narrow candidates within a time range.
             Per-category limit (ROW_NUMBER partition) caps at 50 candidates.
    Phase 2: Only compute embedding distance on the narrowed set.

This reduces embedding computation from O(all_events) to O(50 × N_categories).

Integration: Wrap existing qdrant_store.search() with a pre-filter
that queries SQLite by date range first, then passes sqlite_ids as a
Qdrant filter.

Source: Hindsight retrieval.py (R64 deep steal)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def build_date_prefilter_sql(
    table: str = "events",
    date_column: str = "occurred_at",
    category_column: str = "category",
    categories: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    per_category_limit: int = 50,
) -> tuple[str, list]:
    """Phase 1: Build SQL to narrow candidates by date range + category.

    Returns (sql_string, params_list) for a CTE that returns candidate IDs.

    The query uses ROW_NUMBER PARTITION BY category to cap candidates
    per category, preventing any single high-volume category from
    dominating the candidate set.
    """
    conditions = []
    params: list = []

    if start_date:
        conditions.append(f"{date_column} >= ?")
        params.append(start_date)

    if end_date:
        conditions.append(f"{date_column} <= ?")
        params.append(end_date)

    if categories:
        placeholders = ",".join("?" * len(categories))
        conditions.append(f"{category_column} IN ({placeholders})")
        params.extend(categories)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
    WITH date_ranked AS (
        SELECT id, {category_column},
               ROW_NUMBER() OVER (
                   PARTITION BY {category_column}
                   ORDER BY {date_column} DESC
               ) AS rn
        FROM {table}
        WHERE {where_clause}
    )
    SELECT id FROM date_ranked WHERE rn <= ?
    """
    params.append(per_category_limit)

    return sql, params


def two_phase_recall(
    conn,
    query_text: str,
    *,
    days_back: int = 30,
    categories: list[str] | None = None,
    per_category_limit: int = 50,
    top_k: int = 10,
    table: str = "events",
    date_column: str = "occurred_at",
    category_column: str = "category",
    text_columns: list[str] | None = None,
) -> list[dict]:
    """Two-phase temporal recall: date pre-filter → text similarity.

    Phase 1: SQLite date-indexed query → candidate IDs (fast, O(index))
    Phase 2: Text similarity ranking on candidates only (bounded)

    For full semantic search with embeddings, use two_phase_recall_semantic()
    which routes through Qdrant with sqlite_id pre-filter.

    This version uses LIKE-based text matching as a lightweight fallback
    when Qdrant is unavailable.

    Args:
        conn: SQLite connection
        query_text: search query
        days_back: how far back to search
        categories: filter by these categories (None = all)
        per_category_limit: max candidates per category in Phase 1
        top_k: final results to return
        table: table name
        date_column: column with timestamps
        category_column: column for category partitioning
        text_columns: columns to search in Phase 2 (default: ["title"])

    Returns:
        List of matching rows as dicts, scored and sorted.
    """
    if text_columns is None:
        text_columns = ["title"]

    now = datetime.now(tz=timezone.utc)
    start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")

    # Phase 1: Date pre-filter
    phase1_sql, phase1_params = build_date_prefilter_sql(
        table=table,
        date_column=date_column,
        category_column=category_column,
        categories=categories,
        start_date=start_date,
        per_category_limit=per_category_limit,
    )

    try:
        candidate_rows = conn.execute(phase1_sql, phase1_params).fetchall()
        candidate_ids = [row[0] for row in candidate_rows]
    except Exception as e:
        log.warning("temporal_recall: Phase 1 failed: %s — falling back to full scan", e)
        candidate_ids = None

    if candidate_ids is not None and not candidate_ids:
        return []

    # Phase 2: Text matching on candidates only
    if candidate_ids is not None:
        id_placeholders = ",".join("?" * len(candidate_ids))
        id_filter = f"id IN ({id_placeholders})"
    else:
        id_filter = "1=1"
        candidate_ids = []

    # Build LIKE conditions for text matching
    query_terms = [t.strip() for t in query_text.lower().split() if len(t.strip()) >= 2]

    if not query_terms:
        # No meaningful search terms — return recent candidates
        select_sql = f"SELECT * FROM {table} WHERE {id_filter} ORDER BY {date_column} DESC LIMIT ?"
        params = candidate_ids + [top_k]
        rows = conn.execute(select_sql, params).fetchall()
        return [dict(r) for r in rows]

    # Score by term overlap across text columns
    like_conditions = []
    like_params = []
    for col in text_columns:
        for term in query_terms:
            like_conditions.append(f"(LOWER({col}) LIKE ?)")
            like_params.append(f"%{term}%")

    # Count matches as a rough score
    score_expr = " + ".join(
        f"(CASE WHEN LOWER({col}) LIKE ? THEN 1 ELSE 0 END)"
        for col in text_columns
        for _ in query_terms
    )

    select_sql = f"""
    SELECT *, ({score_expr}) AS match_score
    FROM {table}
    WHERE {id_filter} AND ({" OR ".join(like_conditions)})
    ORDER BY match_score DESC, {date_column} DESC
    LIMIT ?
    """

    # score_expr params + id params + like params + limit
    params = like_params + candidate_ids + like_params + [top_k]

    try:
        rows = conn.execute(select_sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning("temporal_recall: Phase 2 failed: %s", e)
        return []


async def two_phase_recall_semantic(
    conn,
    qdrant_store,
    collection: str,
    query: str,
    *,
    days_back: int = 30,
    categories: list[str] | None = None,
    per_category_limit: int = 50,
    top_k: int = 10,
    table: str = "events",
    date_column: str = "occurred_at",
    category_column: str = "category",
) -> list[dict]:
    """Two-phase recall with Qdrant semantic search in Phase 2.

    Phase 1: SQLite date-indexed query → candidate sqlite_ids
    Phase 2: Qdrant search filtered to candidate sqlite_ids only

    This is the full-power version when Qdrant + embeddings are available.
    """
    now = datetime.now(tz=timezone.utc)
    start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")

    # Phase 1: Date pre-filter via SQLite
    phase1_sql, phase1_params = build_date_prefilter_sql(
        table=table,
        date_column=date_column,
        category_column=category_column,
        categories=categories,
        start_date=start_date,
        per_category_limit=per_category_limit,
    )

    try:
        candidate_rows = conn.execute(phase1_sql, phase1_params).fetchall()
        candidate_ids = [row[0] for row in candidate_rows]
    except Exception as e:
        log.warning("temporal_recall_semantic: Phase 1 failed: %s — searching without pre-filter", e)
        candidate_ids = None

    if candidate_ids is not None and not candidate_ids:
        return []

    # Phase 2: Qdrant semantic search with sqlite_id pre-filter
    filters = {}
    if candidate_ids is not None:
        # Qdrant MatchAny filter on sqlite_id
        filters["sqlite_id"] = candidate_ids

    results = await qdrant_store.search(
        collection=collection,
        query=query,
        top_k=top_k,
        filters=filters if filters else None,
    )

    return results

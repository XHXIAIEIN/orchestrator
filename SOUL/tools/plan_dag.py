import re
import sys
from collections import deque
from pathlib import Path


class CycleError(Exception):
    """Raised when a DAG contains a cycle."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle

    def __str__(self) -> str:
        return "Cycle detected: " + " → ".join(self.cycle)


def build_dag(cards: list[dict]) -> dict[str, set[str]]:
    """Build adjacency dict {card_id: set_of_predecessor_ids}.

    Explicit edges come from card["depends_on"].
    Implicit write-conflict edges: if two cards both create/modify the same
    file, the later card (by numeric card id) depends on the earlier one.
    reads: entries never generate edges.
    """
    # Sort cards by numeric id for deterministic write-conflict ordering
    def numeric_key(card: dict) -> int:
        try:
            return int(card["id"])
        except (ValueError, TypeError):
            return 0

    sorted_cards = sorted(cards, key=numeric_key)

    # Build adjacency dict — start empty, keys for all card ids
    dag: dict[str, set[str]] = {card["id"]: set() for card in cards}

    # Explicit edges
    for card in cards:
        for dep in card.get("depends_on", []):
            dag[card["id"]].add(dep)

    # Implicit write-conflict edges
    file_last_writer: dict[str, str] = {}
    for card in sorted_cards:
        card_id = card["id"]
        writes = set(card.get("creates", [])) | set(card.get("modifies", []))
        for f in writes:
            if f in file_last_writer:
                prior = file_last_writer[f]
                if prior != card_id:
                    dag[card_id].add(prior)
            file_last_writer[f] = card_id

    return dag


def extract_layers(dag: dict[str, set[str]]) -> list[list[str]]:
    """Kahn's algorithm returning layers of card ids.

    Each layer contains card ids that can run in parallel (all predecessors
    are in earlier layers). Within each layer, ids are sorted numerically.
    Raises CycleError with the specific cycle path if a cycle is detected.
    """
    # Compute in-degrees
    in_degree: dict[str, int] = {node: 0 for node in dag}
    for node, preds in dag.items():
        for pred in preds:
            # pred may not be a key if it's an external dep — add it
            if pred not in in_degree:
                in_degree[pred] = 0
                if pred not in dag:
                    dag[pred] = set()
            in_degree[node]  # already counted below
    # Recount properly
    in_degree = {node: 0 for node in dag}
    for node, preds in dag.items():
        for pred in preds:
            if pred not in in_degree:
                in_degree[pred] = 0
            in_degree[node] += 0  # placeholder
    # Correct pass
    in_degree = {node: 0 for node in dag}
    for node in dag:
        for pred in dag[node]:
            # node depends on pred, so node's in_degree increases when pred is done
            pass
    # Clean Kahn implementation
    in_degree = {node: 0 for node in dag}
    for node, preds in dag.items():
        # node has len(preds) predecessors
        in_degree[node] = len(preds)

    layers: list[list[str]] = []
    queue: deque[str] = deque()

    def _numeric_sort_key(node_id: str) -> int:
        try:
            return int(node_id)
        except (ValueError, TypeError):
            return 0

    # Seed queue with nodes that have no predecessors
    for node in sorted(dag.keys(), key=_numeric_sort_key):
        if in_degree[node] == 0:
            queue.append(node)

    visited_count = 0

    while queue:
        # Collect all zero-in-degree nodes as a layer
        layer_nodes = list(queue)
        layer_nodes.sort(key=_numeric_sort_key)
        queue.clear()
        layers.append(layer_nodes)
        visited_count += len(layer_nodes)

        # For each node in the layer, reduce successor in-degrees
        # Successors: nodes that list a layer_node as a predecessor
        for done_node in layer_nodes:
            for node, preds in dag.items():
                if done_node in preds:
                    in_degree[node] -= 1
                    if in_degree[node] == 0:
                        queue.append(node)

    if visited_count != len(dag):
        # Cycle exists — find it via DFS on remaining nodes
        remaining = {n for n in dag if in_degree[n] > 0}
        cycle = _find_cycle(dag, remaining)
        raise CycleError(cycle)

    return layers


def _find_cycle(dag: dict[str, set[str]], remaining: set[str]) -> list[str]:
    """DFS back-edge cycle extraction among remaining (unprocessed) nodes."""
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for pred in dag.get(node, set()):
            if pred not in remaining:
                continue
            if pred in path_set:
                # Found cycle — extract it
                idx = path.index(pred)
                return path[idx:] + [pred]
            if pred not in visited:
                result = dfs(pred)
                if result:
                    return result
        path.pop()
        path_set.discard(node)
        return None

    for start in sorted(remaining):
        if start not in visited:
            result = dfs(start)
            if result:
                return result

    # Fallback — should not happen
    return list(remaining)


def validate_plan_file(plan_path: Path) -> list[list[str]]:
    """Parse plan markdown, extract step cards, build DAG, return layers.

    Extracts steps with creates:/modifies:/reads:/depends on: lines.
    Prints result or raises CycleError.
    """
    text = plan_path.read_text(encoding="utf-8")

    # Split into step blocks by "**Step N.**" headers
    step_pattern = re.compile(r"\*\*Step\s+(\d+)\.\*\*", re.MULTILINE)
    step_matches = list(step_pattern.finditer(text))

    cards: list[dict] = []
    for i, match in enumerate(step_matches):
        step_id = match.group(1)
        start = match.start()
        end = step_matches[i + 1].start() if i + 1 < len(step_matches) else len(text)
        block = text[start:end]

        creates: list[str] = re.findall(r"^\s*-\s*creates:\s*(.+)$", block, re.MULTILINE)
        modifies: list[str] = re.findall(r"^\s*-\s*modifies:\s*(.+)$", block, re.MULTILINE)
        reads: list[str] = re.findall(r"^\s*-\s*reads:\s*(.+)$", block, re.MULTILINE)
        depends_on_raw: list[str] = re.findall(
            r"^\s*depends on:\s*step\s+(\d+)", block, re.MULTILINE | re.IGNORECASE
        )

        cards.append(
            {
                "id": step_id,
                "creates": [v.strip() for v in creates],
                "modifies": [v.strip() for v in modifies],
                "reads": [v.strip() for v in reads],
                "depends_on": depends_on_raw,
            }
        )

    dag = build_dag(cards)
    layers = extract_layers(dag)
    print(f"Plan is DAG-clean. Layers: {layers}")
    return layers


if __name__ == "__main__":
    if len(sys.argv) > 1:
        plan_path = Path(sys.argv[1])
        validate_plan_file(plan_path)

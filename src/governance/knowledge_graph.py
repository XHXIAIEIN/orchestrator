"""Knowledge Graph — track file/module dependencies for blast radius analysis.

Maps which files depend on which, so when a task modifies file X,
we can estimate the blast radius (what else might break).
"""

from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class GraphNode:
    """A node in the knowledge graph (file, module, or concept)."""
    path: str
    node_type: str  # "file", "module", "function", "table"
    imports: list[str] = field(default_factory=list)      # what this depends on
    imported_by: list[str] = field(default_factory=list)   # what depends on this
    last_modified: float = 0.0
    change_frequency: int = 0  # how often this changes


class KnowledgeGraph:
    """Track dependencies between files/modules for blast radius analysis."""

    def __init__(self):
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # from → set(to)
        self._reverse: dict[str, set[str]] = defaultdict(set)  # to → set(from)

    def add_node(self, path: str, node_type: str = "file") -> GraphNode:
        if path not in self._nodes:
            self._nodes[path] = GraphNode(path=path, node_type=node_type)
        return self._nodes[path]

    def add_dependency(self, source: str, target: str):
        """Record that source depends on target (source imports target)."""
        self.add_node(source)
        self.add_node(target)
        self._edges[source].add(target)
        self._reverse[target].add(source)
        self._nodes[source].imports.append(target)
        self._nodes[target].imported_by.append(source)

    def blast_radius(self, changed_file: str, max_depth: int = 3) -> dict:
        """Calculate blast radius: what might break if this file changes.

        Returns:
            {
                "direct": [...],      # files that directly import changed_file
                "transitive": [...],  # files that transitively depend
                "depth": {...},       # file → depth mapping
                "risk_score": float,  # 0-1 based on dependency count + change frequency
            }
        """
        if changed_file not in self._nodes:
            return {"direct": [], "transitive": [], "depth": {}, "risk_score": 0.0}

        # BFS from changed_file through reverse edges
        visited = {}  # path → depth
        queue = [(changed_file, 0)]

        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited[current] = depth

            for dependent in self._reverse.get(current, set()):
                if dependent not in visited:
                    queue.append((dependent, depth + 1))

        # Remove the source file itself
        visited.pop(changed_file, None)

        direct = [p for p, d in visited.items() if d == 1]
        transitive = [p for p, d in visited.items() if d > 1]

        # Risk score: more dependents + higher change frequency = higher risk
        total_affected = len(visited)
        node = self._nodes[changed_file]
        freq_factor = min(node.change_frequency / 10, 1.0)
        risk = min((total_affected / max(len(self._nodes), 1)) + freq_factor * 0.3, 1.0)

        return {
            "direct": direct,
            "transitive": transitive,
            "depth": visited,
            "risk_score": round(risk, 3),
            "total_affected": total_affected,
        }

    def build_from_imports(self, base_dir: str):
        """Scan Python files and build dependency graph from imports.

        Scans `import X` and `from X import Y` statements.
        """
        import os
        import re

        py_files = []
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules", ".trash"}]
            for f in files:
                if f.endswith(".py"):
                    py_files.append(os.path.join(root, f))

        for filepath in py_files:
            rel_path = os.path.relpath(filepath, base_dir).replace("\\", "/")
            self.add_node(rel_path)

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.strip()
                        # from src.core.X import Y
                        m = re.match(r"from\s+([\w.]+)\s+import", line)
                        if m:
                            module = m.group(1).replace(".", "/") + ".py"
                            self.add_dependency(rel_path, module)
                            continue
                        # import src.core.X
                        m = re.match(r"import\s+([\w.]+)", line)
                        if m:
                            module = m.group(1).replace(".", "/") + ".py"
                            self.add_dependency(rel_path, module)
            except Exception:
                continue

    def get_stats(self) -> dict:
        return {
            "nodes": len(self._nodes),
            "edges": sum(len(v) for v in self._edges.values()),
            "most_depended": sorted(
                [(p, len(deps)) for p, deps in self._reverse.items()],
                key=lambda x: -x[1],
            )[:10],
        }

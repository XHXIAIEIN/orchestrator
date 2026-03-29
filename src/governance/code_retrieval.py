"""Layered Code Retrieval — inspired by axe-dig.

3 layers of increasing depth for code understanding:
  L0 Surface: grep/glob — file names and line matches (cheapest)
  L1 Structural: function/class signatures + docstrings
  L2 Contextual: imports, callers, dependencies

Each layer returns progressively more context. Compose layers
based on task complexity: simple bug → L0, refactor → L0+L1+L2.

Token efficiency: L0 ~10 tokens/match, L1 ~50 tokens/fn, L2 ~200 tokens/fn
vs raw file read: ~500 tokens/function. 75-98% savings.

Usage:
    retriever = CodeRetriever(project_root="/project")
    # Quick search
    results = retriever.search("authenticate", layers=[0])
    # Deep analysis
    results = retriever.search("authenticate", layers=[0, 1, 2])
"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result from a code retrieval query."""

    query: str
    layers_used: list[int]
    matches: list[dict] = field(default_factory=list)
    token_estimate: int = 0

    def to_context(self, max_tokens: int = 5000) -> str:
        """Render results as context string, respecting token budget."""
        parts: list[str] = []
        tokens_used = 0
        for match in self.matches:
            entry = self._format_match(match)
            entry_tokens = len(entry) // 3
            if tokens_used + entry_tokens > max_tokens:
                parts.append(
                    f"... ({len(self.matches) - len(parts)} more matches truncated)"
                )
                break
            parts.append(entry)
            tokens_used += entry_tokens
        return "\n".join(parts)

    def _format_match(self, match: dict) -> str:
        lines = [f"### {match.get('file', '?')}:{match.get('line', '?')}"]
        if match.get("type"):
            lines[0] += f" ({match['type']})"
        if match.get("signature"):
            lines.append(f"  `{match['signature']}`")
        if match.get("snippet"):
            lines.append(f"  {match['snippet']}")
        if match.get("imports"):
            lines.append(f"  imports: {', '.join(match['imports'])}")
        if match.get("callers"):
            lines.append(f"  called by: {', '.join(match['callers'][:5])}")
        return "\n".join(lines)


# Patterns for structural extraction
_FUNC_PATTERN = re.compile(
    r"^(\s*)(async\s+)?def\s+(\w+)\s*\((.*?)\)(?:\s*->\s*(.+?))?:", re.MULTILINE
)
_CLASS_PATTERN = re.compile(
    r"^(\s*)class\s+(\w+)(?:\((.*?)\))?:", re.MULTILINE
)
_IMPORT_PATTERN = re.compile(
    r"^(?:from\s+([\w.]+)\s+import\s+(.+)|import\s+([\w.]+))", re.MULTILINE
)


class CodeRetriever:
    """Multi-layer code retrieval engine."""

    def __init__(self, project_root: str = "."):
        self.root = Path(project_root)
        self._file_extensions = {".py", ".js", ".ts", ".yaml", ".yml", ".md"}

    def search(
        self,
        query: str,
        layers: list[int] | None = None,
        file_pattern: str = "**/*.py",
    ) -> RetrievalResult:
        """Search codebase with specified layers.

        Args:
            query: Search term (function name, keyword, etc.)
            layers: Which layers to use [0, 1, 2]. Default: [0]
            file_pattern: Glob pattern for files to search.

        Returns:
            RetrievalResult with matches from all requested layers.
        """
        layers = layers or [0]
        result = RetrievalResult(query=query, layers_used=layers)

        # L0: Surface search (grep-like)
        if 0 in layers:
            self._search_l0(query, file_pattern, result)

        # L1: Structural (function/class signatures)
        if 1 in layers:
            self._search_l1(query, file_pattern, result)

        # L2: Contextual (imports, callers)
        if 2 in layers:
            self._enrich_l2(query, result)

        result.token_estimate = sum(len(str(m)) // 3 for m in result.matches)
        return result

    def _search_l0(self, query: str, pattern: str, result: RetrievalResult):
        """L0 Surface: find files and lines matching query."""
        try:
            for filepath in self.root.glob(pattern):
                if not filepath.is_file():
                    continue
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                except (OSError, UnicodeDecodeError):
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    if query.lower() in line.lower():
                        result.matches.append(
                            {
                                "file": str(filepath.relative_to(self.root)),
                                "line": i,
                                "snippet": line.strip()[:200],
                                "layer": 0,
                            }
                        )
        except Exception as e:
            log.debug("code_retrieval L0 error: %s", e)

    def _search_l1(self, query: str, pattern: str, result: RetrievalResult):
        """L1 Structural: find function/class definitions matching query."""
        try:
            for filepath in self.root.glob(pattern):
                if not filepath.is_file():
                    continue
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                except (OSError, UnicodeDecodeError):
                    continue
                rel_path = str(filepath.relative_to(self.root))

                # Functions
                for m in _FUNC_PATTERN.finditer(content):
                    func_name = m.group(3)
                    if query.lower() in func_name.lower():
                        line_num = content[: m.start()].count("\n") + 1
                        params = m.group(4).strip()
                        ret = m.group(5)
                        sig = f"def {func_name}({params})"
                        if ret:
                            sig += f" -> {ret.strip()}"
                        # Get docstring
                        docstring = self._extract_docstring(content, m.end())
                        match_data: dict = {
                            "file": rel_path,
                            "line": line_num,
                            "type": "function",
                            "signature": sig,
                            "layer": 1,
                        }
                        if docstring:
                            match_data["snippet"] = docstring
                        result.matches.append(match_data)

                # Classes
                for m in _CLASS_PATTERN.finditer(content):
                    class_name = m.group(2)
                    if query.lower() in class_name.lower():
                        line_num = content[: m.start()].count("\n") + 1
                        bases = m.group(3) or ""
                        sig = f"class {class_name}"
                        if bases:
                            sig += f"({bases.strip()})"
                        result.matches.append(
                            {
                                "file": rel_path,
                                "line": line_num,
                                "type": "class",
                                "signature": sig,
                                "layer": 1,
                            }
                        )
        except Exception as e:
            log.debug("code_retrieval L1 error: %s", e)

    def _enrich_l2(self, query: str, result: RetrievalResult):
        """L2 Contextual: add import and caller info to existing matches."""
        # Collect unique files from existing matches
        files: set[str] = set()
        for m in result.matches:
            files.add(m.get("file", ""))

        for rel_path in files:
            filepath = self.root / rel_path
            if not filepath.exists():
                continue
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            # Extract imports
            imports: list[str] = []
            for m in _IMPORT_PATTERN.finditer(content):
                module = m.group(1) or m.group(3)
                if module:
                    imports.append(module)

            # Find callers of the query term in other files
            callers = self._find_callers(query, rel_path)

            # Enrich existing matches
            for match in result.matches:
                if match.get("file") == rel_path and match.get("layer", 0) < 2:
                    if imports:
                        match["imports"] = imports[:10]
                    if callers:
                        match["callers"] = callers[:5]

    def _find_callers(self, func_name: str, source_file: str) -> list[str]:
        """Find files that call a function (simple grep-based)."""
        callers: list[str] = []
        pattern = re.compile(rf"\b{re.escape(func_name)}\s*\(")
        try:
            for filepath in self.root.glob("**/*.py"):
                if not filepath.is_file():
                    continue
                rel = str(filepath.relative_to(self.root))
                if rel == source_file:
                    continue
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                    if pattern.search(content):
                        callers.append(rel)
                except (OSError, UnicodeDecodeError):
                    continue
        except Exception:
            pass
        return callers

    def _extract_docstring(self, content: str, pos: int) -> str:
        """Extract docstring after a function/class definition."""
        remaining = content[pos : pos + 500]
        # Look for triple-quoted string
        m = re.match(r'\s*\n\s*"""(.*?)"""', remaining, re.DOTALL)
        if m:
            return m.group(1).strip()[:200]
        m = re.match(r"\s*\n\s*'''(.*?)'''", remaining, re.DOTALL)
        if m:
            return m.group(1).strip()[:200]
        return ""

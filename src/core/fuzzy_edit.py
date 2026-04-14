"""渐进式模糊文本匹配与替换 — 9 级策略链。

偷自 Hermes Agent v0.9 fuzzy_match.py (R59)。

当精确字符串查找失败时，依次尝试宽松度递增的策略，直到找到匹配或全部策略
耗尽为止。设计用于 AI 代码编辑场景：LLM 生成的 old_string 可能含有空白差异、
智能引号、转义字符等与原始文件不完全一致的情况。

策略链（auto 模式按序尝试，首次命中即停）：
  1. exact              — str.find() 基准
  2. line_trimmed       — 逐行 strip() 后匹配
  3. whitespace_normalized — 合并行内连续空白，附位置映射回原文
  4. indentation_flexible  — 忽略缩进（lstrip 所有行）
  5. escape_normalized     — 处理 \\n \\t \\r 字面转义
  6. trimmed_boundary      — 仅 strip 搜索块首尾行
  7. unicode_normalized    — 智能引号/破折号/省略号 → ASCII，附字符级位置映射
  8. block_anchor          — 首尾行精确 + 中间 SequenceMatcher（阈值 0.50/0.70）
  9. context_aware         — 滑动窗口，80% 行相似度阈值

每个策略返回 list[tuple[int, int]]，即匹配在**原始文本**中的 (start, end) 偏移量。

用法示例：
    from src.core.fuzzy_edit import fuzzy_find, fuzzy_replace, FuzzyMatchResult

    positions = fuzzy_find(source, old_code)
    new_source = fuzzy_replace(source, old_code, new_code)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 公开数据类型
# ---------------------------------------------------------------------------


@dataclass
class FuzzyMatchResult:
    """模糊匹配的结果。"""

    strategy: str                           # 命中的策略名称
    positions: List[Tuple[int, int]]        # 在原始文本中的 (start, end) 列表
    confidence: float                       # 置信度：1.0 = 精确，越模糊越低


# ---------------------------------------------------------------------------
# 策略置信度表
# ---------------------------------------------------------------------------

_STRATEGY_CONFIDENCE: dict[str, float] = {
    "exact":                  1.00,
    "line_trimmed":           0.95,
    "whitespace_normalized":  0.90,
    "indentation_flexible":   0.85,
    "escape_normalized":      0.82,
    "trimmed_boundary":       0.78,
    "unicode_normalized":     0.75,
    "block_anchor":           0.65,
    "context_aware":          0.55,
}

# 策略执行顺序（auto 模式）
_STRATEGY_ORDER: list[str] = [
    "exact",
    "line_trimmed",
    "whitespace_normalized",
    "indentation_flexible",
    "escape_normalized",
    "trimmed_boundary",
    "unicode_normalized",
    "block_anchor",
    "context_aware",
]

# ---------------------------------------------------------------------------
# Unicode 规范化映射表
# ---------------------------------------------------------------------------

# 将"花哨"字符映射到 ASCII 等价物
# 这些字符在 LLM 输出中很常见（智能引号、破折号、省略号）
_UNICODE_REPLACEMENTS: list[tuple[str, str]] = [
    ("\u2018", "'"),   # 左单引号
    ("\u2019", "'"),   # 右单引号 / 撇号
    ("\u201c", '"'),   # 左双引号
    ("\u201d", '"'),   # 右双引号
    ("\u2013", "-"),   # 短破折号
    ("\u2014", "--"),  # 长破折号（注意：双字符替换，映射表需处理长度变化）
    ("\u2026", "..."), # 省略号（同上，三字符替换）
    ("\u00a0", " "),   # 不换行空格
    ("\u2212", "-"),   # 减号（数学）
    ("\u00b4", "'"),   # 尖音符
    ("\u0060", "'"),   # 反引号作撇号（宽松处理）
]


def _build_orig_to_norm_map(original: str) -> tuple[str, list[int]]:
    """构建原始文本 → 规范化文本的字符级位置映射。

    由于 Unicode 替换可能改变字符长度（如 '…' → '...' 变长），
    规范化文本的位置不能简单等于原始文本的位置。

    返回 (normalized_text, orig_positions)，其中：
      normalized_text       — 替换后的文本
      orig_positions[i]     — 规范化文本位置 i 对应原始文本的位置

    举例（\u2014 → '--'）：
      original  = "a\u2014b"   → "a--b"
      orig_pos  = [0, 1, 1, 2]   # 位置 1 和 2 都映射回原始位置 1

    反向查找：要把 norm 中的 (ns, ne) 转回 orig 中的 (os, oe)：
      os = orig_positions[ns]
      oe = orig_positions[ne - 1] + 1  （需要 ne > ns）
    """
    # 先构建替换规则：(orig_char, norm_str)
    replace_map: dict[str, str] = dict(_UNICODE_REPLACEMENTS)

    normalized_chars: list[str] = []
    orig_positions: list[int] = []  # orig_positions[norm_idx] = orig_idx

    for orig_idx, ch in enumerate(original):
        replacement = replace_map.get(ch, ch)
        for norm_ch in replacement:
            normalized_chars.append(norm_ch)
            orig_positions.append(orig_idx)

    normalized_text = "".join(normalized_chars)
    return normalized_text, orig_positions


def _norm_span_to_orig(
    orig_positions: list[int],
    original: str,
    ns: int,
    ne: int,
) -> tuple[int, int]:
    """把规范化文本中的 (ns, ne) 区间转回原始文本坐标。

    ns: 规范化文本匹配起始（包含）
    ne: 规范化文本匹配结束（不包含）
    """
    if ns >= len(orig_positions):
        # 理论上不会发生，但防御一下
        return ns, ne

    orig_start = orig_positions[ns]

    if ne == 0:
        return orig_start, orig_start

    # ne - 1 是匹配区间最后一个字符在规范化文本中的位置
    last_norm_idx = ne - 1
    if last_norm_idx < len(orig_positions):
        orig_last_char = orig_positions[last_norm_idx]
    else:
        orig_last_char = len(original) - 1

    # orig_end 是原始文本中最后一个匹配字符的下一位置
    orig_end = orig_last_char + 1
    return orig_start, orig_end


# ---------------------------------------------------------------------------
# 策略 1：精确匹配
# ---------------------------------------------------------------------------


def _strategy_exact(text: str, pattern: str) -> list[tuple[int, int]]:
    """str.find() 循环，O(n*m) 但无任何预处理开销。"""
    results: list[tuple[int, int]] = []
    start = 0
    plen = len(pattern)
    while True:
        pos = text.find(pattern, start)
        if pos == -1:
            break
        results.append((pos, pos + plen))
        # 向前移动 1 以允许重叠匹配（实际编辑场景中很少见，但保持一致）
        start = pos + 1
    return results


# ---------------------------------------------------------------------------
# 策略 2：逐行 strip 匹配
# ---------------------------------------------------------------------------


def _strategy_line_trimmed(text: str, pattern: str) -> list[tuple[int, int]]:
    """strip 每行后做逐行比较。

    核心思路：
      1. 把 text 和 pattern 都按行分割。
      2. 在 text_lines（已 strip）中滑动窗口搜索 pattern_lines（已 strip）。
      3. 命中时，从原始 text 行的起止偏移量还原出 (start, end)。
    """
    text_lines = text.splitlines(keepends=True)   # 保留换行符以还原位置
    pattern_lines_stripped = [ln.strip() for ln in pattern.splitlines()]

    # 过滤掉 pattern 首尾的空行（LLM 有时会多加换行）
    while pattern_lines_stripped and pattern_lines_stripped[0] == "":
        pattern_lines_stripped.pop(0)
    while pattern_lines_stripped and pattern_lines_stripped[-1] == "":
        pattern_lines_stripped.pop()

    if not pattern_lines_stripped:
        return []

    plen = len(pattern_lines_stripped)
    tlen = len(text_lines)

    # 预计算每行在 text 中的字节偏移
    offsets: list[int] = []
    acc = 0
    for ln in text_lines:
        offsets.append(acc)
        acc += len(ln)
    offsets.append(acc)  # sentinel

    results: list[tuple[int, int]] = []

    for i in range(tlen - plen + 1):
        # 检查 plen 行是否全部匹配（strip 后）
        match = all(
            text_lines[i + j].strip() == pattern_lines_stripped[j]
            for j in range(plen)
        )
        if match:
            start = offsets[i]
            end = offsets[i + plen]  # 末行（含换行符）之后
            results.append((start, end))

    return results


# ---------------------------------------------------------------------------
# 策略 3：行内空白规范化
# ---------------------------------------------------------------------------


def _normalize_inline_whitespace(s: str) -> tuple[str, list[int]]:
    """将行内连续 [ \\t]+ 替换为单个空格，构建位置映射。

    返回 (normalized, orig_positions)，语义同 _build_orig_to_norm_map。
    行分隔符（\\n、\\r\\n）原样保留，不参与合并。
    """
    normalized_chars: list[str] = []
    orig_positions: list[int] = []
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        if ch in (" ", "\t"):
            # 收集连续空白（仅限行内空白，不包括换行）
            j = i
            while j < n and s[j] in (" ", "\t"):
                j += 1
            # 用单个空格代表整段空白，orig_positions 记录区间起始
            normalized_chars.append(" ")
            orig_positions.append(i)
            i = j
        else:
            normalized_chars.append(ch)
            orig_positions.append(i)
            i += 1

    return "".join(normalized_chars), orig_positions


def _strategy_whitespace_normalized(text: str, pattern: str) -> list[tuple[int, int]]:
    """合并行内连续空白后匹配，命中后映射回原始坐标。"""
    norm_text, text_orig_pos = _normalize_inline_whitespace(text)
    norm_pattern, _ = _normalize_inline_whitespace(pattern)

    if not norm_pattern:
        return []

    results: list[tuple[int, int]] = []
    start = 0
    plen = len(norm_pattern)

    while True:
        pos = norm_text.find(norm_pattern, start)
        if pos == -1:
            break

        # 规范化坐标 → 原始坐标
        orig_start = text_orig_pos[pos]

        norm_end = pos + plen
        if norm_end <= len(text_orig_pos):
            # 末字符在原始文本中的位置 +1 = end（exclusive）
            orig_end = text_orig_pos[norm_end - 1] + 1
            # 但我们需要找到原始文本中对应的完整末尾
            # 规范化末位 -1 对应原始的某个字符；原始 end 应向右延伸到
            # 下一个"未被合并"的位置，即 text_orig_pos[norm_end - 1] + 1
            # 如果末字符是空格合并的起点，需要找到原始连续空白段的结尾
            raw_end_char_idx = text_orig_pos[norm_end - 1]
            # 向右扫描，跳过被合并进去的空白
            while raw_end_char_idx + 1 < len(text) and text[raw_end_char_idx + 1] in (" ", "\t"):
                # 检查这段空白是否已被合并进规范化匹配末尾
                # 只有当 norm_end 处的规范化字符不是空格时才需要扩展
                # 安全起见：不扩展，只取第一个字符位置 +1
                break
            orig_end = raw_end_char_idx + 1
        else:
            orig_end = len(text)

        results.append((orig_start, orig_end))
        start = pos + 1

    return results


# ---------------------------------------------------------------------------
# 策略 4：忽略缩进
# ---------------------------------------------------------------------------


def _strategy_indentation_flexible(text: str, pattern: str) -> list[tuple[int, int]]:
    """lstrip 所有行后逐行比较，忽略任意缩进差异。

    与 line_trimmed 的区别：line_trimmed 同时 strip 左右，
    此策略仅 lstrip（保留行尾空格，更精确）。
    """
    text_lines = text.splitlines(keepends=True)
    pattern_lines_lstripped = [ln.lstrip() for ln in pattern.splitlines()]

    # 清理 pattern 首尾空行
    while pattern_lines_lstripped and pattern_lines_lstripped[0].rstrip("\r\n") == "":
        pattern_lines_lstripped.pop(0)
    while pattern_lines_lstripped and pattern_lines_lstripped[-1].rstrip("\r\n") == "":
        pattern_lines_lstripped.pop()

    if not pattern_lines_lstripped:
        return []

    plen = len(pattern_lines_lstripped)
    tlen = len(text_lines)

    offsets: list[int] = []
    acc = 0
    for ln in text_lines:
        offsets.append(acc)
        acc += len(ln)
    offsets.append(acc)

    results: list[tuple[int, int]] = []

    for i in range(tlen - plen + 1):
        match = all(
            text_lines[i + j].lstrip() == pattern_lines_lstripped[j]
            for j in range(plen)
        )
        if match:
            results.append((offsets[i], offsets[i + plen]))

    return results


# ---------------------------------------------------------------------------
# 策略 5：转义字符规范化
# ---------------------------------------------------------------------------

# 匹配字面转义序列：\n \t \r（即代码中写的反斜杠+字母，而非实际控制字符）
_ESCAPE_RE = re.compile(r"\\[ntr]")
_ESCAPE_MAP = {"\\n": "\n", "\\t": "\t", "\\r": "\r"}


def _expand_escapes(s: str) -> str:
    """将字面转义序列 \\n \\t \\r 替换为对应的控制字符。"""
    return _ESCAPE_RE.sub(lambda m: _ESCAPE_MAP[m.group()], s)


def _strategy_escape_normalized(text: str, pattern: str) -> list[tuple[int, int]]:
    """展开 pattern 中的字面转义后，用展开版本在原始 text 中精确匹配。

    注意：text 不做处理（文件内容不应含字面 \\n），只处理 pattern。
    如果展开前后 pattern 相同（无转义），直接返回空（避免与 exact 重复）。
    """
    expanded = _expand_escapes(pattern)
    if expanded == pattern:
        # 没有转义，此策略无增量价值
        return []
    return _strategy_exact(text, expanded)


# ---------------------------------------------------------------------------
# 策略 6：首尾行 strip
# ---------------------------------------------------------------------------


def _strategy_trimmed_boundary(text: str, pattern: str) -> list[tuple[int, int]]:
    """只 strip pattern 的首行和末行，中间行保持原样。

    适用场景：LLM 在引用代码块时，在首尾多加了空白，但中间行准确。
    """
    p_lines = pattern.splitlines()
    if not p_lines:
        return []

    # 只 strip 首尾
    if len(p_lines) == 1:
        normalized_pattern = p_lines[0].strip()
    else:
        p_lines[0] = p_lines[0].strip()
        p_lines[-1] = p_lines[-1].strip()
        normalized_pattern = "\n".join(p_lines)

    if normalized_pattern == pattern:
        return []

    return _strategy_exact(text, normalized_pattern)


# ---------------------------------------------------------------------------
# 策略 7：Unicode 规范化
# ---------------------------------------------------------------------------


def _strategy_unicode_normalized(text: str, pattern: str) -> list[tuple[int, int]]:
    """将智能引号、破折号、省略号等替换为 ASCII 等价物后匹配。

    同时规范化 text 和 pattern，命中后通过字符级位置映射还原原始坐标。
    """
    norm_text, text_orig_pos = _build_orig_to_norm_map(text)
    norm_pattern, _ = _build_orig_to_norm_map(pattern)

    if norm_pattern == pattern and norm_text == text:
        # 两边都没有 Unicode 特殊字符，此策略无增量价值
        return []

    results: list[tuple[int, int]] = []
    start = 0
    plen = len(norm_pattern)

    while True:
        pos = norm_text.find(norm_pattern, start)
        if pos == -1:
            break

        orig_start, orig_end = _norm_span_to_orig(text_orig_pos, text, pos, pos + plen)
        results.append((orig_start, orig_end))
        start = pos + 1

    return results


# ---------------------------------------------------------------------------
# 策略 8：首尾行锚定 + SequenceMatcher 中间行
# ---------------------------------------------------------------------------

_BLOCK_ANCHOR_THRESHOLD_PARTIAL = 0.50   # 中间行个别行相似度下限
_BLOCK_ANCHOR_THRESHOLD_OVERALL = 0.70   # 所有中间行平均相似度下限


def _line_similarity(a: str, b: str) -> float:
    """两行的 SequenceMatcher 相似度（0.0~1.0）。"""
    return SequenceMatcher(None, a, b).ratio()


def _strategy_block_anchor(text: str, pattern: str) -> list[tuple[int, int]]:
    """首行和末行要求精确匹配，中间行用 SequenceMatcher 宽松匹配。

    阈值：
      - 每行相似度 >= 0.50（_BLOCK_ANCHOR_THRESHOLD_PARTIAL）
      - 所有中间行平均相似度 >= 0.70（_BLOCK_ANCHOR_THRESHOLD_OVERALL）

    对于单行 pattern，降级为精确匹配（无"中间行"概念）。
    对于两行 pattern，只检查首行和末行精确匹配。
    """
    text_lines = text.splitlines(keepends=True)
    pattern_lines = pattern.splitlines()

    # 清理 pattern 首尾空行
    while pattern_lines and pattern_lines[0].strip() == "":
        pattern_lines.pop(0)
    while pattern_lines and pattern_lines[-1].strip() == "":
        pattern_lines.pop()

    if not pattern_lines:
        return []

    plen = len(pattern_lines)
    tlen = len(text_lines)

    # 单行：直接精确匹配
    if plen == 1:
        return _strategy_exact(text, pattern_lines[0])

    first_line = pattern_lines[0]
    last_line = pattern_lines[-1]
    middle_lines = pattern_lines[1:-1]

    offsets: list[int] = []
    acc = 0
    for ln in text_lines:
        offsets.append(acc)
        acc += len(ln)
    offsets.append(acc)

    # 预处理：text_lines 去掉行尾换行符用于比较
    text_lines_stripped = [ln.rstrip("\r\n") for ln in text_lines]

    results: list[tuple[int, int]] = []

    for i in range(tlen - plen + 1):
        # 检查首行和末行精确匹配（strip 后）
        if text_lines_stripped[i].strip() != first_line.strip():
            continue
        if text_lines_stripped[i + plen - 1].strip() != last_line.strip():
            continue

        # 若无中间行（2 行 pattern），直接命中
        if not middle_lines:
            results.append((offsets[i], offsets[i + plen]))
            continue

        # 检查中间行相似度
        sims: list[float] = []
        ok = True
        for j, pat_mid in enumerate(middle_lines):
            txt_mid = text_lines_stripped[i + 1 + j]
            sim = _line_similarity(txt_mid.strip(), pat_mid.strip())
            if sim < _BLOCK_ANCHOR_THRESHOLD_PARTIAL:
                ok = False
                break
            sims.append(sim)

        if not ok:
            continue

        avg_sim = sum(sims) / len(sims)
        if avg_sim >= _BLOCK_ANCHOR_THRESHOLD_OVERALL:
            results.append((offsets[i], offsets[i + plen]))

    return results


# ---------------------------------------------------------------------------
# 策略 9：滑动窗口上下文感知
# ---------------------------------------------------------------------------

_CONTEXT_AWARE_LINE_THRESHOLD = 0.80   # 每行相似度下限


def _strategy_context_aware(text: str, pattern: str) -> list[tuple[int, int]]:
    """滑动窗口：要求窗口内每行相似度 >= 80%。

    比 block_anchor 更宽松：首尾行不要求精确，全部行均用相似度衡量。
    适用场景：代码被轻微重构（变量重命名、类型注解添加）后的匹配。
    """
    text_lines = text.splitlines(keepends=True)
    pattern_lines = [ln.strip() for ln in pattern.splitlines()]

    # 清理 pattern 首尾空行
    while pattern_lines and pattern_lines[0] == "":
        pattern_lines.pop(0)
    while pattern_lines and pattern_lines[-1] == "":
        pattern_lines.pop()

    if not pattern_lines:
        return []

    plen = len(pattern_lines)
    tlen = len(text_lines)

    offsets: list[int] = []
    acc = 0
    for ln in text_lines:
        offsets.append(acc)
        acc += len(ln)
    offsets.append(acc)

    text_lines_stripped = [ln.strip() for ln in text_lines]

    results: list[tuple[int, int]] = []

    for i in range(tlen - plen + 1):
        ok = True
        for j in range(plen):
            sim = _line_similarity(text_lines_stripped[i + j], pattern_lines[j])
            if sim < _CONTEXT_AWARE_LINE_THRESHOLD:
                ok = False
                break
        if ok:
            results.append((offsets[i], offsets[i + plen]))

    return results


# ---------------------------------------------------------------------------
# 策略调度表
# ---------------------------------------------------------------------------

_STRATEGY_FNS: dict[str, object] = {
    "exact":                 _strategy_exact,
    "line_trimmed":          _strategy_line_trimmed,
    "whitespace_normalized": _strategy_whitespace_normalized,
    "indentation_flexible":  _strategy_indentation_flexible,
    "escape_normalized":     _strategy_escape_normalized,
    "trimmed_boundary":      _strategy_trimmed_boundary,
    "unicode_normalized":    _strategy_unicode_normalized,
    "block_anchor":          _strategy_block_anchor,
    "context_aware":         _strategy_context_aware,
}


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def fuzzy_find(
    text: str,
    pattern: str,
    *,
    strategy: str = "auto",
) -> list[tuple[int, int]]:
    """在 text 中查找 pattern，返回原始文本中的 (start, end) 位置列表。

    Args:
        text:     被搜索的原始文本。
        pattern:  要查找的模式字符串。
        strategy: 策略名称，或 "auto"（依序尝试所有策略，首次命中即停）。

    Returns:
        list of (start, end) — 空列表表示未找到。

    Raises:
        ValueError: strategy 不在已知策略列表中。
    """
    if not pattern:
        return []

    if strategy == "auto":
        for name in _STRATEGY_ORDER:
            fn = _STRATEGY_FNS[name]
            try:
                matches = fn(text, pattern)  # type: ignore[operator]
            except Exception:
                logger.debug("fuzzy_find: strategy %r raised an exception", name, exc_info=True)
                continue
            if matches:
                logger.debug(
                    "fuzzy_find: strategy=%r found %d match(es)",
                    name, len(matches),
                )
                return matches
        logger.debug("fuzzy_find: all strategies exhausted, no match found")
        return []

    if strategy not in _STRATEGY_FNS:
        raise ValueError(
            f"Unknown strategy {strategy!r}. "
            f"Valid strategies: {list(_STRATEGY_FNS)}"
        )

    fn = _STRATEGY_FNS[strategy]
    return fn(text, pattern)  # type: ignore[operator]


def fuzzy_find_with_result(
    text: str,
    pattern: str,
    *,
    strategy: str = "auto",
) -> Optional[FuzzyMatchResult]:
    """fuzzy_find 的增强版，返回 FuzzyMatchResult（含策略名和置信度）。

    strategy="auto" 时遍历策略链，首次命中即返回。
    """
    if not pattern:
        return None

    if strategy == "auto":
        for name in _STRATEGY_ORDER:
            fn = _STRATEGY_FNS[name]
            try:
                matches = fn(text, pattern)  # type: ignore[operator]
            except Exception:
                logger.debug(
                    "fuzzy_find_with_result: strategy %r raised an exception",
                    name, exc_info=True,
                )
                continue
            if matches:
                return FuzzyMatchResult(
                    strategy=name,
                    positions=matches,
                    confidence=_STRATEGY_CONFIDENCE.get(name, 0.5),
                )
        return None

    if strategy not in _STRATEGY_FNS:
        raise ValueError(
            f"Unknown strategy {strategy!r}. "
            f"Valid strategies: {list(_STRATEGY_FNS)}"
        )

    fn = _STRATEGY_FNS[strategy]
    matches = fn(text, pattern)  # type: ignore[operator]
    if not matches:
        return None
    return FuzzyMatchResult(
        strategy=strategy,
        positions=matches,
        confidence=_STRATEGY_CONFIDENCE.get(strategy, 0.5),
    )


def fuzzy_replace(
    text: str,
    old: str,
    new: str,
    *,
    replace_all: bool = False,
) -> str:
    """用 new 替换 text 中的 old，使用渐进式模糊匹配定位。

    替换逻辑：
      1. 调用 fuzzy_find 定位所有匹配位置。
      2. 如果 replace_all=False 且匹配数 > 1 → 抛出 ValueError（拒绝歧义替换）。
      3. 按**从右到左**顺序应用替换，以保证较早位置的偏移量不受影响。
      4. 如果未找到任何匹配，原样返回 text（不抛出异常）。

    Args:
        text:        原始文本。
        old:         要替换的旧字符串（使用模糊匹配定位）。
        new:         替换后的新字符串。
        replace_all: True = 替换所有匹配；False = 只允许单一匹配，否则报错。

    Returns:
        替换后的文本，或原文（未找到匹配时）。

    Raises:
        ValueError: replace_all=False 且找到多于 1 个匹配位置。
    """
    if not old:
        return text

    matches = fuzzy_find(text, old)

    if not matches:
        logger.debug("fuzzy_replace: no match found, returning original text unchanged")
        return text

    if not replace_all and len(matches) > 1:
        raise ValueError(
            f"fuzzy_replace: found {len(matches)} matches for the given pattern "
            f"but replace_all=False. Set replace_all=True to replace all occurrences, "
            f"or make the pattern more specific.\n"
            f"Match positions: {matches}"
        )

    # 从右到左应用替换：右侧替换不会改变左侧位置的偏移量
    # 若从左到右替换，每次替换后剩余位置的偏移量都需要重新计算（且 new/old 长度
    # 不同时必然出错）。从右到左则完全规避这个问题。
    sorted_matches = sorted(matches, reverse=True)  # 按 start 降序

    result = text
    for start, end in sorted_matches:
        result = result[:start] + new + result[end:]

    logger.debug(
        "fuzzy_replace: replaced %d occurrence(s) (replace_all=%r)",
        len(sorted_matches), replace_all,
    )
    return result

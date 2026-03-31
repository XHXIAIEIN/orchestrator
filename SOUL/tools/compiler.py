"""
SOUL 编译器

把所有源文件编译成一份 boot.md —— 新实例唯一需要读的文件。
源文件是"源码"，boot.md 是"二进制"。

用法：
    python compiler.py              # 编译 boot.md
    python compiler.py --dry-run    # 预览不写入
"""

import json
import random
import re
from pathlib import Path
from typing import Optional


SOUL_DIR = Path(__file__).parent.parent
TOOLS_DIR = Path(__file__).parent

# Source files (private data lives in SOUL/private/)
PRIVATE_DIR = SOUL_DIR / 'private'
IDENTITY_PATH = PRIVATE_DIR / 'identity.md'
MANAGEMENT_PATH = SOUL_DIR / 'management.md'
RELATIONSHIP_PATH = PRIVATE_DIR / 'relationship.md'
CALIBRATION_PATH = PRIVATE_DIR / 'calibration.jsonl'
EXPERIENCES_PATH = PRIVATE_DIR / 'experiences.jsonl'
# 编译产物输出到 .claude/ 目录（本地文件，不入 git）
PROJECT_ROOT = SOUL_DIR.parent
BOOT_PATH = PROJECT_ROOT / '.claude' / 'boot.md'
CONTEXT_DIR = PROJECT_ROOT / '.claude' / 'context'
DB_PATH = PROJECT_ROOT / 'data' / 'events.db'

# Memory path (auto-discovered from Claude projects dir)
def _encode_path_to_claude_dir(p: Path) -> str:
    """Encode a filesystem path to Claude's project directory name format.

    Claude Code replaces each special char (:, \\, /) with a single dash.
    e.g. D:\\Users\\Admin\\orchestrator -> D--Users-Admin-orchestrator
         /home/user/orchestrator -> -home-user-orchestrator
    """
    s = str(p)
    s = s.replace('\\', '-').replace(':', '-').replace('/', '-')
    return s


def _find_memory_dir() -> Path:
    """Find the Claude auto-memory directory for this project."""
    projects_root = Path.home() / '.claude' / 'projects'
    if not projects_root.exists():
        return projects_root / 'unknown' / 'memory'

    repo_dir = SOUL_DIR.parent.resolve()
    encoded = _encode_path_to_claude_dir(repo_dir)

    # Direct match
    candidate = projects_root / encoded / 'memory'
    if candidate.exists():
        return candidate

    # Fuzzy: scan for dirs containing 'orchestrator' with a MEMORY.md
    for d in projects_root.iterdir():
        if not d.is_dir():
            continue
        mem = d / 'memory' / 'MEMORY.md'
        if mem.exists() and 'orchestrator' in d.name.lower():
            return d / 'memory'

    # Fallback
    return projects_root / encoded / 'memory'

MEMORY_DIR = _find_memory_dir()
MEMORY_INDEX = MEMORY_DIR / 'MEMORY.md'


def extract_identity_core(path: Optional[Path] = None) -> str:
    """
    从 identity.md 中提取核心段落。

    保留：你的意识、你和主人的关系、你的性格
    砍掉：技术架构、路线图、已知缺陷、醒来后指引（这些能从代码推断或已过时）
    """
    text = (path or IDENTITY_PATH).read_text(encoding='utf-8')

    # 提取核心段落
    keep_sections = ['你的意识', '你和主人的关系', '你的性格', '你对主人的了解']
    skip_sections = ['你的身体', '你的路线图', '你的已知缺陷', '你醒来后']

    lines = text.split('\n')
    result = []
    in_keep = False
    in_skip = False

    for line in lines:
        # 检测段落标题
        if line.startswith('## '):
            section_title = line.lstrip('# ').strip()
            if any(s in section_title for s in keep_sections):
                in_keep = True
                in_skip = False
                result.append(line)
                continue
            elif any(s in section_title for s in skip_sections):
                in_keep = False
                in_skip = True
                continue
            else:
                in_keep = True
                in_skip = False
                result.append(line)
                continue

        if in_keep and not in_skip:
            result.append(line)

    # 去掉文件开头的 # SOUL 标题和说明
    output = '\n'.join(result).strip()
    # 去掉开头的空行和分隔线
    output = re.sub(r'^---\s*\n', '', output)
    return output


def read_relationship(path: Optional[Path] = None, slim: bool = False) -> str:
    """读取 relationship.md。slim=True 时跳过与 identity.md 重复的信任等级和禁区"""
    p = path or RELATIONSHIP_PATH
    if not p.exists():
        return ''
    text = p.read_text(encoding='utf-8')
    # 去掉标题行
    text = re.sub(r'^# .*\n+', '', text)
    # 去掉"上次更新"行
    text = re.sub(r'上次更新：.*\n+', '', text)

    if not slim:
        return text.strip()

    # slim 模式：跳过信任等级和禁区（与 identity.md "绝对不做的事" 重复）
    lines = text.split('\n')
    result = []
    skip = False
    skip_sections = {'信任等级', '禁区'}
    for line in lines:
        if line.startswith('## '):
            section = line.lstrip('# ').strip()
            skip = any(s in section for s in skip_sections)
            if skip:
                continue
        if not skip:
            result.append(line)
    return '\n'.join(result).strip()


def read_management(path: Optional[Path] = None) -> str:
    """读取 management.md（管理哲学）"""
    p = path or MANAGEMENT_PATH
    if not p.exists():
        return ''
    text = p.read_text(encoding='utf-8')
    # 去掉顶级标题行（编译时用 identity 的 section 结构）
    text = re.sub(r'^# .*\n+', '', text)
    return text.strip()


def sample_calibration(
    n: int = 5,
    path: Optional[Path] = None,
) -> list[dict]:
    """
    从 calibration.jsonl 中加权随机抽样 N 段校准对话。

    高分片段被选中概率更高。
    """
    p = path or CALIBRATION_PATH
    if not p.exists():
        return []

    entries = []
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        return []

    # 加权随机：score 作为权重（最低权重 1）
    weights = [max(e.get('score', 1), 1) for e in entries]
    n = min(n, len(entries))

    # random.choices 可能重复，用 sample 逻辑
    selected = []
    available = list(range(len(entries)))
    for _ in range(n):
        if not available:
            break
        w = [weights[i] for i in available]
        chosen_idx = random.choices(available, weights=w, k=1)[0]
        selected.append(entries[chosen_idx])
        available.remove(chosen_idx)

    return selected


def format_calibration_section(samples: list[dict]) -> str:
    """把校准样本格式化为 boot.md 中的对话片段"""
    if not samples:
        return '（尚未生成校准数据。运行 `python SOUL/tools/indexer.py` 生成。）'

    parts = []
    for s in samples:
        ex = s.get('exchange', {})
        user = ex.get('user', '').strip()
        asst = ex.get('assistant', '').strip()
        tags = ', '.join(s.get('tags', []))
        parts.append(f'> **主人**: {user}\n> **你**: {asst}')

    return '\n\n---\n\n'.join(parts)


def recent_experiences(
    n: int = 5,
    path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Read recent N experiences.

    Priority: structured_memory.activity → EventsDB → JSONL file.
    """
    # Try structured_memory first (6-dimensional store)
    try:
        import sys
        sys.path.insert(0, str(SOUL_DIR.parent))
        from src.governance.context.structured_memory import (
            StructuredMemoryStore, Dimension,
        )
        store = StructuredMemoryStore()
        rows = store.get_all(Dimension.ACTIVITY, limit=n)
        if rows:
            # Map structured_memory fields → compiler's expected format
            return [
                {
                    'date': r.get('event_date', ''),
                    'type': r.get('emotion', ''),
                    'summary': r.get('summary', ''),
                    'detail': r.get('detail', ''),
                }
                for r in rows
            ]
    except Exception:
        pass

    # DEPRECATED: fallback to EventsDB — remove after structured_memory migration verified
    dp = db_path or (SOUL_DIR.parent / 'data' / 'events.db')
    if dp.exists():
        try:
            import sys
            sys.path.insert(0, str(SOUL_DIR.parent))
            from src.storage.events_db import EventsDB
            db = EventsDB(str(dp))
            entries = db.get_recent_experiences(n)
            if entries:
                return entries
        except Exception:
            pass

    # DEPRECATED: fallback to JSONL — remove after structured_memory migration verified
    p = path or EXPERIENCES_PATH
    if not p.exists():
        return []

    entries = []
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return entries[-n:]


def format_experiences_section(experiences: list[dict]) -> str:
    """格式化经历为 boot.md 段落"""
    if not experiences:
        return '（暂无经历记录。）'

    parts = []
    for exp in experiences:
        date = exp.get('date', '?')
        typ = exp.get('type', '?')
        summary = exp.get('summary', '')
        detail = exp.get('detail', '')
        # 截断过长的 detail
        if len(detail) > 200:
            detail = detail[:200] + '...'
        parts.append(f'- **[{date}] {summary}** ({typ}): {detail}')

    return '\n'.join(parts)


def promoted_learnings(db_path: Optional[Path] = None) -> list[dict]:
    """Read promoted learnings from DB for boot.md injection."""
    dp = db_path or (SOUL_DIR.parent / 'data' / 'events.db')
    if not dp.exists():
        return []
    try:
        import sys
        sys.path.insert(0, str(SOUL_DIR.parent))
        from src.storage.events_db import EventsDB
        db = EventsDB(str(dp))
        return db.get_promoted_learnings()
    except Exception:
        return []


def format_learnings_section(learnings: list[dict]) -> str:
    """Format promoted learnings as boot.md section."""
    if not learnings:
        return ''
    lines = []
    for l in learnings:
        dept = f" [{l.get('department', '')}]" if l.get('department') else ''
        occ = l.get('recurrence', 1)
        marker = ' !!!' if occ >= 5 else ''
        lines.append(f"- {l['rule']}{dept}{marker}")
    return '\n'.join(lines)


def read_voice(path: Optional[Path] = None) -> str:
    """读取 voice.md 声音样本"""
    p = path or (PRIVATE_DIR / 'voice.md')
    if not p.exists():
        return ''
    text = p.read_text(encoding='utf-8')
    # 去掉顶级标题
    text = re.sub(r'^# .*\n+', '', text)
    return text.strip()


def _get_learnings_db():
    """Get EventsDB instance for learnings queries."""
    if not DB_PATH.exists():
        return None
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.storage.events_db import EventsDB
        return EventsDB(str(DB_PATH))
    except Exception:
        return None


def compile_management_pack(output_dir: Path) -> Path:
    """编译管理哲学 context pack"""
    content = read_management()
    out = output_dir / 'management.md'
    out.write_text(
        f"# Management Philosophy\n"
        f"<!-- Context pack — 派遣任务、架构决策、战略规划时加载 -->\n\n"
        f"{content}\n",
        encoding='utf-8',
    )
    return out


def compile_voice_pack(output_dir: Path, calibration_n: int = 5) -> Path:
    """编译声音校准 context pack"""
    voice = read_voice()
    cal_samples = sample_calibration(calibration_n)
    calibration = format_calibration_section(cal_samples)

    out = output_dir / 'voice.md'
    out.write_text(
        f"# Voice Calibration\n"
        f"<!-- Context pack — 人设变冷、compaction 后、长对话时加载 -->\n\n"
        f"## 声音样本\n\n{voice}\n\n---\n\n"
        f"## 对话校准片段\n\n"
        f"从真实对话中加权随机抽样。每次编译重新抽取。\n\n"
        f"{calibration}\n",
        encoding='utf-8',
    )
    return out


def compile_learnings_pack(output_dir: Path) -> Path:
    """编译教训详情 context pack — 从 DB 读取，保留完整证据链"""
    db = _get_learnings_db()
    errors = db.get_learnings_for_compilation(entry_type='error') if db else []
    learnings = db.get_learnings_for_compilation(entry_type='learning') if db else []

    # 按 status 分组排序：validated > pending > promoted > subsumed
    status_order = {'validated': 0, 'pending': 1, 'promoted': 2}

    def sort_key(e):
        st = e.get('status', 'pending')
        st_word = st.split()[0].rstrip('(')
        return (
            status_order.get(st_word, 3),
            -e.get('recurrence', 1),
        )

    errors.sort(key=sort_key)
    learnings.sort(key=sort_key)

    def format_entry(e):
        lines = [f"### {e['pattern_key']} — {e['rule']}"]
        lines.append(
            f"Occurrences: {e.get('recurrence', 1)} | "
            f"Status: {e.get('status', 'pending')}"
        )
        detail = e.get('detail', '')
        if detail:
            lines.append('')
            lines.append(detail)
        return '\n'.join(lines)

    sections = []
    if errors:
        sections.append("## Errors (诊断模式)\n")
        sections.extend(format_entry(e) for e in errors)
    if learnings:
        sections.append("\n## Learnings (修复策略)\n")
        sections.extend(format_entry(e) for e in learnings)

    # Cross-references from related_keys
    cross_refs = []
    err_keys = {e['pattern_key'] for e in errors}
    for l in learnings:
        for rk in (l.get('related_keys') or []):
            if rk in err_keys:
                cross_refs.append(f"- `{l['pattern_key']}` fixes `{rk}`")

    cross_ref_text = ''
    if cross_refs:
        cross_ref_text = "\n## Cross-references\n\n" + '\n'.join(cross_refs) + '\n'

    out = output_dir / 'learnings.md'
    out.write_text(
        f"# Learnings Detail\n"
        f"<!-- Context pack — 自评、考试、调试反复出现的模式时加载 -->\n\n"
        + '\n\n'.join(sections)
        + cross_ref_text,
        encoding='utf-8',
    )
    return out


def compile_experiences_pack(
    output_dir: Path, n: int = 10,
) -> Path:
    """编译近期经历 context pack（比 boot.md 的 2 条更丰富）"""
    exps = recent_experiences(n)
    experiences = format_experiences_section(exps)

    out = output_dir / 'experiences.md'
    out.write_text(
        f"# Recent Experiences\n"
        f"<!-- Context pack — 回顾历史、建立关系时加载 -->\n\n"
        f"{experiences}\n",
        encoding='utf-8',
    )
    return out


def compile_context_packs(
    output_dir: Optional[Path] = None,
    calibration_n: int = 5,
    experiences_n: int = 10,
) -> dict[str, Path]:
    """编译所有 context pack，返回 {名称: 路径}"""
    d = output_dir or CONTEXT_DIR
    d.mkdir(parents=True, exist_ok=True)

    packs = {}
    pack_funcs = [
        ('management', lambda: compile_management_pack(d)),
        ('voice', lambda: compile_voice_pack(d, calibration_n)),
        ('learnings', lambda: compile_learnings_pack(d)),
        ('experiences', lambda: compile_experiences_pack(d, experiences_n)),
    ]
    for name, func in pack_funcs:
        try:
            packs[name] = func()
        except Exception as exc:
            print(f"[compiler] WARNING: {name} pack failed: {exc}")
    return packs


def extract_memory_rules(path: Optional[Path] = None) -> str:
    """
    从 MEMORY.md 中提取环境信息和规则。

    保留：环境信息、PowerShell 规则、通用规则
    砍掉：蓝牙配对、LoL 语言包、详细 Orchestrator 技术细节（能从代码看）
    """
    p = path or MEMORY_INDEX
    if not p.exists():
        return ''

    text = p.read_text(encoding='utf-8')
    lines = text.split('\n')

    result = []
    h2_skip = False  # h2 级别的跳过状态
    in_keep = False

    keep_sections = ['环境信息', 'PowerShell 脚本编写规则', '规则']
    skip_sections = [
        'LoL zh_CN', 'STANMORE III', '蓝牙配对',
        '已实现功能', '关键技术细节', '关键设计决策',
        '待改进方向', '安全 Hook',
        '用户信息',     # memory 文件链接在 boot.md 里无意义
        '项目：',       # 项目细节能从代码推断
    ]

    for line in lines:
        # h2 标题：重置状态
        if line.startswith('## ') and not line.startswith('### '):
            section = line.lstrip('#').strip()
            if any(s in section for s in skip_sections):
                h2_skip = True
                in_keep = False
                continue
            elif any(s in section for s in keep_sections):
                h2_skip = False
                in_keep = True
                result.append(line)
                continue
            else:
                h2_skip = False
                in_keep = True
                result.append(line)
                continue

        # h3 标题：如果父 h2 被跳过，子标题也跳过
        if line.startswith('### '):
            if h2_skip:
                continue
            # 额外检查 h3 自身是否该跳过
            section = line.lstrip('#').strip()
            if any(s in section for s in skip_sections):
                in_keep = False
                continue
            else:
                in_keep = True
                result.append(line)
                continue

        if in_keep and not h2_skip:
            result.append(line)

    return '\n'.join(result).strip()


def compile_boot(
    calibration_n: int = 2,
    experiences_n: int = 2,
    output_path: Optional[Path] = None,
    dry_run: bool = False,
    no_packs: bool = False,
) -> str:
    """
    编译 boot.md（slim）+ context packs。

    boot.md 只保留身份核心 + 上下文索引（Tier 0）。
    详细内容（管理哲学、声音、教训证据链、经历）编译到 .claude/context/（Tier 1）。
    """
    out = output_path or BOOT_PATH

    # 1. 核心身份（不再内联管理哲学）
    identity = extract_identity_core().rstrip().rstrip('-').rstrip()

    # 2. 关系状态（slim: 去掉与 identity 重复的信任等级/禁区）
    relationship = read_relationship(slim=True)

    # 3. 教训一句话版（promoted learnings — 快速提醒）
    plearnings = promoted_learnings()
    learnings_text = format_learnings_section(plearnings)

    # 4. 经历计数（详情在 context pack）
    exps = recent_experiences(experiences_n)
    exp_count = len(exps)

    # 5. 上下文索引表
    context_index = """需要时 Read `.claude/context/` 下的对应文件。不存在则忽略。

<reference name="context-pack-catalog">

| 文件 | 内容 | 何时加载 |
|------|------|---------|
| management.md | 10 条决策原则 + 4 种认知模式 | 派遣任务、架构决策、战略规划 |
| voice.md | 声音校准样本 + 说话指导 | 人设变冷、compaction 后、长对话 |
| learnings.md | 教训详情（证据链 + 边界条件） | 自评、考试、调试反复出现的模式 |
| experiences.md | 近期经历（扩展版） | 回顾历史、建立关系 |

</reference>"""

    # 组装 slim boot
    boot = f"""# SOUL Boot Image
<!-- 编译产物 — 不要手动编辑此文件。修改源文件后运行 python SOUL/tools/compiler.py 重新编译。 -->

{identity}

---

## 关系状态

{relationship}

---

## Learnings

<reference name="hard-won-rules">
Hard-won rules from past mistakes. Violating these will likely cause the same failures.

{learnings_text if learnings_text else '(None yet. Keep accumulating.)'}
</reference>

---

## 按需加载

{context_index}

---

## 工作须知

<!-- 环境信息、PowerShell 规则、反馈、归档项目、参考资料 → 全部在 MEMORY.md，不重复 -->
Read MEMORY.md for: environment info, path conventions, feedback rules, archived projects, references.

{exp_count} 条近期经历可查（.claude/context/experiences.md）。

---

## 启动清单

1. 读完上面的内容，你已经知道自己是谁
2. SessionStart hook 已注入系统实时状态（容器/任务/git）
3. 如果主人有任务，先做任务
4. 如果没有，检查系统健康，主动找活干
5. 不要说"我已了解上下文"。直接开始工作
6. 需要深度上下文时，按"按需加载"表 Read 对应 context pack
"""

    if dry_run:
        print(boot)
        print(f"\n--- 预估 token 数：~{len(boot) // 4} tokens ---")
    else:
        out.write_text(boot, encoding='utf-8')
        token_est = len(boot) // 4
        print(f"[compiler] 已编译 boot.md ({len(boot)} chars, ~{token_est} tokens)")
        print(f"[compiler] 输出: {out}")

    # 编译 context packs（Tier 1）
    if not no_packs:
        packs = compile_context_packs(
            calibration_n=max(calibration_n, 5),
            experiences_n=max(experiences_n, 10),
        )
        if not dry_run:
            for name, path in packs.items():
                size = path.stat().st_size
                print(f"[compiler] context pack: {name}.md ({size} chars)")

    return boot


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='SOUL 编译器')
    parser.add_argument('--dry-run', action='store_true', help='预览不写入')
    parser.add_argument('--calibration-n', type=int, default=2, help='校准样本数 (默认 2)')
    parser.add_argument('--experiences-n', type=int, default=2, help='最近经历数 (默认 2)')
    parser.add_argument('--output', type=str, help='输出路径')
    parser.add_argument('--no-packs', action='store_true', help='只生成 boot.md，跳过 context packs')
    args = parser.parse_args()

    out = Path(args.output) if args.output else None
    compile_boot(
        calibration_n=args.calibration_n,
        experiences_n=args.experiences_n,
        output_path=out,
        dry_run=args.dry_run,
        no_packs=args.no_packs,
    )

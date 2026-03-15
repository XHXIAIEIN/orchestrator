"""
SOUL 对话索引器

扫描 ~/.claude/projects/ 下的历史对话 JSONL 文件，
切片为 user+assistant 对，调用 scorer 打分，
取 top N 存入 SOUL/calibration.jsonl。
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

# 确保能 import scorer
sys.path.insert(0, str(Path(__file__).parent))
from scorer import Exchange, score_exchanges


# Orchestrator 相关的项目目录名
ORCHESTRATOR_PROJECT_DIRS = [
    'D--Agent',
    'D--Agent-orchestrator',
    'D--Users-Administrator-Documents-GitHub-orchestrator',
]

# Claude projects 根目录
CLAUDE_PROJECTS_ROOT = Path.home() / '.claude' / 'projects'

# 输出路径
SOUL_DIR = Path(__file__).parent.parent
CALIBRATION_PATH = SOUL_DIR / 'calibration.jsonl'


def find_session_files(
    projects_root: Optional[Path] = None,
    project_dirs: Optional[list[str]] = None,
) -> list[Path]:
    """找到所有相关的 JSONL 会话文件"""
    root = projects_root or CLAUDE_PROJECTS_ROOT
    dirs = project_dirs or ORCHESTRATOR_PROJECT_DIRS

    files = []
    for dirname in dirs:
        dirpath = root / dirname
        if not dirpath.is_dir():
            continue
        for f in dirpath.iterdir():
            if f.suffix == '.jsonl' and f.is_file():
                files.append(f)

    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def extract_text(message: dict) -> tuple[str, bool]:
    """
    从 JSONL 消息中提取文本内容。

    Returns:
        (text, has_tool_use) — 纯文本内容和是否包含工具调用
    """
    content = message.get('message', {}).get('content', '')

    if isinstance(content, str):
        return content, False

    if isinstance(content, list):
        has_tool = any(
            block.get('type') in ('tool_use', 'tool_result')
            for block in content
        )
        texts = [
            block.get('text', '')
            for block in content
            if block.get('type') == 'text'
        ]
        return ' '.join(texts).strip(), has_tool

    return '', False


def parse_session(filepath: Path) -> list[Exchange]:
    """
    解析一个 JSONL 会话文件，提取 user+assistant 对话对。

    策略：
    - 优先提取纯文本对话（无工具调用）
    - 对有工具调用的消息，提取其文本部分（如果有且足够长）
    - 跳过纯工具调用（无文本内容）和系统噪音
    """
    session_id = filepath.stem[:8]
    exchanges = []

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            messages = []
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get('type') in ('user', 'assistant'):
                        messages.append(obj)
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        return []

    # 按对话轮提取：每个 user 消息 → 向后扫描到下一个 user 前 → 取最后一条有文本的 assistant
    # 这样能捕获工具链结束后的"人话"
    user_indices = [i for i, m in enumerate(messages) if m.get('type') == 'user']

    for idx, ui in enumerate(user_indices):
        # 确定这一轮的范围：当前 user 到下一个 user 之前
        next_ui = user_indices[idx + 1] if idx + 1 < len(user_indices) else len(messages)

        u_text, u_tool = extract_text(messages[ui])

        # 在这一轮里找最后一条有文本的 assistant 消息
        best_a_text = ''
        best_a_line = ui
        for j in range(ui + 1, next_ui):
            if messages[j].get('type') != 'assistant':
                continue
            a_text, _ = extract_text(messages[j])
            if a_text.strip() and len(a_text.strip()) >= 20:
                best_a_text = a_text
                best_a_line = j

        if not best_a_text.strip() or not u_text.strip():
            continue

        # user 侧过滤
        if u_tool and len(u_text.strip()) < 10:
            continue

        # 跳过系统噪音
        if 'Base directory for this skill' in u_text:
            continue
        if '<system-reminder>' in u_text and len(u_text) < 50:
            continue
        if '<task-notification>' in u_text:
            continue
        if u_text.strip().startswith('<') and u_text.strip().endswith('>'):
            continue

        exchanges.append(Exchange(
            user=u_text,
            assistant=best_a_text,
            line_index=ui,
            session_id=session_id,
        ))

    return exchanges


def run_indexer(
    top_n: int = 50,
    projects_root: Optional[Path] = None,
    project_dirs: Optional[list[str]] = None,
    output_path: Optional[Path] = None,
) -> list[dict]:
    """
    完整的索引流程：扫描 → 解析 → 评分 → 输出 top N。

    Returns:
        写入的校准条目列表
    """
    out = output_path or CALIBRATION_PATH

    # 1. 找文件
    files = find_session_files(projects_root, project_dirs)
    print(f"[indexer] 找到 {len(files)} 个会话文件")

    # 2. 解析所有对话（按内容去重）
    all_exchanges: list[Exchange] = []
    seen_hashes: set[str] = set()
    dupes = 0
    for f in files:
        exchanges = parse_session(f)
        for ex in exchanges:
            # 用 user+assistant 前100字符做去重 key
            dedup_key = (ex['user'][:100] + '|||' + ex['assistant'][:100])
            if dedup_key in seen_hashes:
                dupes += 1
                continue
            seen_hashes.add(dedup_key)
            all_exchanges.append(ex)

    print(f"[indexer] 提取了 {len(all_exchanges)} 个对话片段（去重 {dupes} 条）")

    if not all_exchanges:
        print("[indexer] 没有对话片段，跳过")
        return []

    # 3. 评分
    scored = score_exchanges(all_exchanges)

    # 4. 取 top N（只保留正分）
    top = [s for s in scored[:top_n] if s['score'] > 0]
    print(f"[indexer] 正分片段: {sum(1 for s in scored if s['score'] > 0)}, 取 top {len(top)}")

    # 5. 写入 calibration.jsonl
    entries = []
    for item in top:
        ex = item['exchange']
        entry = {
            'id': f"{ex['session_id']}_L{ex['line_index']}",
            'score': item['score'],
            'tags': item['tags'],
            'exchange': {
                'user': ex['user'][:500],       # 截断过长内容
                'assistant': ex['assistant'][:1000],
            },
            'source_session': ex['session_id'],
        }
        entries.append(entry)

    with open(out, 'w', encoding='utf-8') as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    print(f"[indexer] 已写入 {len(entries)} 条到 {out}")

    # 打印 top 5 预览
    print("\n[indexer] Top 5 预览:")
    for item in entries[:5]:
        print(f"  #{item['score']:+d} [{', '.join(item['tags'])}]")
        print(f"    User: {item['exchange']['user'][:80]}")
        print(f"    Asst: {item['exchange']['assistant'][:80]}")
        print()

    return entries


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='SOUL 对话索引器')
    parser.add_argument('--top', type=int, default=50, help='保留 top N 条 (默认 50)')
    parser.add_argument('--output', type=str, help='输出路径 (默认 SOUL/calibration.jsonl)')
    args = parser.parse_args()

    out = Path(args.output) if args.output else None
    run_indexer(top_n=args.top, output_path=out)

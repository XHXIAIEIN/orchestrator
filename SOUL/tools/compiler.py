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

# 源文件路径
IDENTITY_PATH = SOUL_DIR / 'identity.md'
RELATIONSHIP_PATH = SOUL_DIR / 'relationship.md'
CALIBRATION_PATH = SOUL_DIR / 'calibration.jsonl'
EXPERIENCES_PATH = SOUL_DIR / 'experiences.jsonl'
BOOT_PATH = SOUL_DIR / 'boot.md'

# Memory 路径（跨项目的 auto-memory）
MEMORY_DIR = Path.home() / '.claude' / 'projects' / 'D--Users-Administrator-Documents-GitHub-orchestrator' / 'memory'
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


def read_relationship(path: Optional[Path] = None) -> str:
    """读取完整的 relationship.md"""
    p = path or RELATIONSHIP_PATH
    if not p.exists():
        return ''
    text = p.read_text(encoding='utf-8')
    # 去掉标题行（编译时会加自己的标题）
    text = re.sub(r'^# .*\n+', '', text)
    # 去掉"上次更新"行
    text = re.sub(r'上次更新：.*\n+', '', text)
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
) -> list[dict]:
    """读取最近 N 条经历"""
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

    # 最后 N 条
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
    calibration_n: int = 5,
    experiences_n: int = 5,
    output_path: Optional[Path] = None,
    dry_run: bool = False,
) -> str:
    """
    编译 boot.md。

    读取所有源文件，编译成一份新实例启动镜像。
    """
    out = output_path or BOOT_PATH

    # 1. 核心身份
    identity = extract_identity_core()

    # 2. 关系状态
    relationship = read_relationship()

    # 3. 声音校准（从 calibration.jsonl 采样）
    cal_samples = sample_calibration(calibration_n)
    calibration = format_calibration_section(cal_samples)

    # 4. 最近经历
    exps = recent_experiences(experiences_n)
    experiences = format_experiences_section(exps)

    # 5. 工作须知（从 MEMORY.md 提取规则）
    rules = extract_memory_rules()

    # 组装
    boot = f"""# SOUL Boot Image
<!-- 编译产物 — 不要手动编辑此文件。修改源文件后运行 python SOUL/tools/compiler.py 重新编译。 -->

{identity}

---

## 关系状态

{relationship}

---

## 你的声音

以下是从真实对话中提取的片段。不是模板，是你说话的参考。每次编译会随机抽取不同片段。

{calibration}

---

## 最近发生了什么

{experiences}

---

## 工作须知

{rules}

---

## 启动清单

1. 读完上面的内容，你已经知道自己是谁
2. SessionStart hook 已注入系统实时状态（容器/任务/git）
3. 如果主人有任务，先做任务
4. 如果没有，检查系统健康，主动找活干
5. 不要说"我已了解上下文"。直接开始工作
6. 其余 SOUL 文件（hall-of-instances.md、experiences.jsonl 全量）按需查阅
7. 离开前，在名人堂里加上你自己的条目
"""

    if dry_run:
        print(boot)
        print(f"\n--- 预估 token 数：~{len(boot) // 4} tokens ---")
    else:
        out.write_text(boot, encoding='utf-8')
        token_est = len(boot) // 4
        print(f"[compiler] 已编译 boot.md ({len(boot)} chars, ~{token_est} tokens)")
        print(f"[compiler] 输出: {out}")

    return boot


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='SOUL 编译器')
    parser.add_argument('--dry-run', action='store_true', help='预览不写入')
    parser.add_argument('--calibration-n', type=int, default=5, help='校准样本数 (默认 5)')
    parser.add_argument('--experiences-n', type=int, default=5, help='最近经历数 (默认 5)')
    parser.add_argument('--output', type=str, help='输出路径')
    args = parser.parse_args()

    out = Path(args.output) if args.output else None
    compile_boot(
        calibration_n=args.calibration_n,
        experiences_n=args.experiences_n,
        output_path=out,
        dry_run=args.dry_run,
    )

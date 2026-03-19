"""
去AI味后处理管道

检测中文文本中的 AI 特征短语，给出替换建议，输出改写版本。
规则式检测，不依赖外部 API。

用法：
    python deai_writer.py input.txt                  # 检测并输出标注版
    python deai_writer.py input.txt -o output.txt    # 写入文件
    python deai_writer.py input.txt --rewrite        # 输出改写版（直接替换）
    echo "文本内容" | python deai_writer.py -        # 从 stdin 读取
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ============================================================
# 1. AI 特征短语词典
#    分类：套话连接词 / 过度总结 / 虚假亲切 / 学术腔 / 排比堆砌
# ============================================================

@dataclass
class AIPattern:
    """一条 AI 特征模式"""
    pattern: str          # 正则
    category: str         # 分类标签
    description: str      # 为什么这是 AI 味
    suggestions: list[str] = field(default_factory=list)  # 替换建议（空=直接删）

# --- 套话连接词 ---
FILLER_CONNECTORS = [
    AIPattern(r'值得注意的是[，,]?', 'filler', '假装重要的空话',
             ['', '但', '不过']),
    AIPattern(r'众所周知[，,]?', 'filler', '没人这么说话',
             ['', '大家都知道']),
    AIPattern(r'总的来说[，,]?', 'filler', '典型 AI 总结句式',
             ['说白了', '简单讲', '']),
    AIPattern(r'综上所述[，,]?', 'filler', '论文结尾才用',
             ['所以', '总之', '']),
    AIPattern(r'总而言之[，,]?', 'filler', '和"综上所述"一样假',
             ['所以', '']),
    AIPattern(r'需要指出的是[，,]?', 'filler', '没人需要你指出',
             ['', '但是']),
    AIPattern(r'不可否认[，,]?', 'filler', '欲扬先抑的套路',
             ['确实', '']),
    AIPattern(r'毋庸置疑[，,]?', 'filler', '用力过猛',
             ['', '确实']),
    AIPattern(r'在当今(?:社会|时代|世界)[，,]?', 'filler', '高考作文开头',
             ['现在', '如今', '']),
    AIPattern(r'(?:首先|其次|最后|此外|另外)[，,]', 'filler', '列表式写作，人不这么说话',
             []),  # 建议：重写段落结构，无法简单替换
    AIPattern(r'与此同时[，,]?', 'filler', '新闻联播腔',
             ['同时', '而且', '']),
    AIPattern(r'除此之外[，,]?', 'filler', '可以更口语',
             ['另外', '还有', '']),
    AIPattern(r'从而', 'filler', '因果关系不需要这么正式',
             ['这样就', '于是', '所以']),
]

# --- 过度总结/升华 ---
OVER_SUMMARIZE = [
    AIPattern(r'这(?:不仅|既).{2,30}(?:更是|也是|还是).{2,30}', '升华', '「不仅是X，更是Y」是 AI 最爱的升华句式',
             []),
    AIPattern(r'归根结底[，,]?', 'summary', '过度总结',
             ['说到底', '']),
    AIPattern(r'本质上[来说讲]?[，,]?', 'summary', '假装深刻',
             ['其实', '说白了', '']),
    AIPattern(r'从(?:本质|根本)上(?:来?看|来说)[，,]?', 'summary', '学术假深刻',
             ['其实', '']),
    AIPattern(r'在某种程度上[，,]?', 'summary', '模糊的废话',
             ['', '有点']),
    AIPattern(r'可以说[，,]?', 'summary', '去掉也不影响意思',
             ['']),
]

# --- 虚假亲切/鸡汤 ---
FAKE_WARMTH = [
    AIPattern(r'让我们(?:一起)?', 'warmth', 'AI 式号召',
             ['我们', '']),
    AIPattern(r'希望(?:本文|这篇|以上|这些).{0,10}(?:帮助|启发|启示)', 'warmth', 'AI 结尾经典句',
             []),
    AIPattern(r'相信.{0,10}(?:一定|必将|能够)', 'warmth', '鸡汤式许诺',
             []),
    AIPattern(r'(?:激发|释放|赋能|助力)', 'warmth', '企业新闻稿用语',
             []),
    AIPattern(r'(?:赋予|注入).{0,6}(?:新的|全新|无限)', 'warmth', '空洞的修饰',
             []),
]

# --- 学术腔/翻译腔 ---
ACADEMIC_TONE = [
    AIPattern(r'(?:进行|开展|实施)(?:了)?(?:深入|全面|系统|详细)', 'academic', '名词化动词，翻译腔',
             []),
    AIPattern(r'(?:具有|拥有).{0,10}(?:重要|深远|显著|积极)', 'academic', '官方报告体',
             []),
    AIPattern(r'对于.{2,15}(?:而言|来说)', 'academic', '可以更直接',
             []),
    AIPattern(r'在.{2,20}(?:方面|层面|维度|领域)', 'academic', '"在X方面"是 AI 最爱的句式框架',
             []),
    AIPattern(r'(?:提供|提出)了.{0,10}(?:新的|全新|独特)', 'academic', '论文摘要体',
             []),
    AIPattern(r'(?:旨在|致力于|力求)', 'academic', '使命宣言体',
             []),
]

# --- 排比/堆砌 ---
PARALLEL_PILE = [
    AIPattern(r'无论是.{2,20}还是.{2,20}(?:都|均)', 'parallel', 'AI 式排比',
             []),
    AIPattern(r'不仅.{2,20}而且.{2,20}', 'parallel', '如果不是在对比，就是在堆砌',
             []),
    AIPattern(r'既.{2,15}又.{2,15}', 'parallel', '排比堆砌嫌疑',
             []),
]

# --- 情感过载 ---
EMOTION_OVERLOAD = [
    AIPattern(r'[！!]{2,}', 'emotion', '多余的感叹号',
             ['！']),
    AIPattern(r'(?:真的)?非常(?:非常)?', 'emotion', '"非常"出现频率过高是 AI 标记',
             ['很', '挺', '']),
    AIPattern(r'深深[地的]', 'emotion', '用力过猛',
             ['']),
    AIPattern(r'令人(?:惊叹|震撼|印象深刻|兴奋|感动)', 'emotion', '夸张修饰',
             []),
]

ALL_PATTERNS = (
    FILLER_CONNECTORS + OVER_SUMMARIZE + FAKE_WARMTH
    + ACADEMIC_TONE + PARALLEL_PILE + EMOTION_OVERLOAD
)


# ============================================================
# 2. 结构特征检测（不靠关键词，靠文本结构）
# ============================================================

def _detect_structural_issues(text: str) -> list[dict]:
    """检测结构性 AI 特征"""
    issues = []
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

    # 段落首句高度相似（AI 喜欢每段开头用同一种句式）
    openers = []
    for p in paragraphs:
        first_sent = re.split(r'[。！？\n]', p)[0]
        if first_sent:
            openers.append(first_sent)

    if len(openers) >= 3:
        # 检测"首先...其次...最后..."结构
        seq_markers = ['首先', '其次', '再次', '最后', '第一', '第二', '第三']
        seq_count = sum(1 for o in openers if any(o.startswith(m) for m in seq_markers))
        if seq_count >= 3:
            issues.append({
                'type': 'structure',
                'description': f'列表式行文：{seq_count} 个段落用序号词开头，像 PPT 不像文章',
                'suggestion': '打乱顺序，用具体场景或故事串联，而不是列清单',
            })

    # 段落长度过于均匀（人写的文章段落长短不一）
    if len(paragraphs) >= 4:
        lengths = [len(p) for p in paragraphs]
        avg = sum(lengths) / len(lengths)
        if avg > 0:
            variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
            cv = (variance ** 0.5) / avg  # 变异系数
            if cv < 0.3:
                issues.append({
                    'type': 'structure',
                    'description': f'段落长度过于均匀（变异系数 {cv:.2f}），像模板生成',
                    'suggestion': '有的段落可以只有一两句话，有的可以展开讲个故事',
                })

    # 结尾段升华检测
    if paragraphs:
        last = paragraphs[-1]
        uplift_words = ['未来', '展望', '期待', '相信', '让我们', '希望', '总之', '综上']
        hits = sum(1 for w in uplift_words if w in last)
        if hits >= 2:
            issues.append({
                'type': 'structure',
                'description': f'结尾段有 {hits} 个升华词，像演讲稿收尾',
                'suggestion': '好文章结尾是具体的——一个细节、一句对话、一个画面，不是口号',
            })

    return issues


# ============================================================
# 3. 检测引擎
# ============================================================

@dataclass
class Detection:
    """一处检测结果"""
    line_no: int
    col_start: int
    col_end: int
    matched_text: str
    category: str
    description: str
    suggestions: list[str]


def detect(text: str) -> tuple[list[Detection], list[dict], dict]:
    """
    对文本运行全部检测规则。

    Returns:
        (detections, structural_issues, stats)
    """
    detections = []
    category_counts: dict[str, int] = {}

    lines = text.split('\n')
    for line_no, line in enumerate(lines, 1):
        for ap in ALL_PATTERNS:
            for m in re.finditer(ap.pattern, line):
                d = Detection(
                    line_no=line_no,
                    col_start=m.start(),
                    col_end=m.end(),
                    matched_text=m.group(),
                    category=ap.category,
                    description=ap.description,
                    suggestions=ap.suggestions,
                )
                detections.append(d)
                category_counts[ap.category] = category_counts.get(ap.category, 0) + 1

    structural = _detect_structural_issues(text)
    for s in structural:
        category_counts['structure'] = category_counts.get('structure', 0) + 1

    # AI 味浓度评分（0-100）
    char_count = len(text)
    if char_count == 0:
        score = 0
    else:
        # 每千字检出数
        density = len(detections) / (char_count / 1000)
        # 结构问题额外加分
        density += len(structural) * 2
        # 映射到 0-100（经验值：密度 10 以上基本全是 AI 写的）
        score = min(100, int(density * 10))

    stats = {
        'total_detections': len(detections),
        'structural_issues': len(structural),
        'ai_score': score,
        'char_count': char_count,
        'category_breakdown': category_counts,
    }

    return detections, structural, stats


# ============================================================
# 4. 输出格式化
# ============================================================

CATEGORY_LABELS = {
    'filler': '🗑️ 套话',
    'summary': '📝 过度总结',
    '升华': '🚀 强行升华',
    'warmth': '🤗 虚假亲切',
    'academic': '🎓 学术腔',
    'parallel': '📋 排比堆砌',
    'emotion': '💢 情感过载',
    'structure': '🏗️ 结构问题',
}

AI_SCORE_LABELS = [
    (20, '✅ 基本没有 AI 味'),
    (40, '🟡 轻微 AI 味，稍作修改即可'),
    (60, '🟠 明显 AI 味，需要重写部分段落'),
    (80, '🔴 浓重 AI 味，建议大幅改写'),
    (100, '💀 纯 AI 生成，建议从头用自己的话重写'),
]


def format_report(
    text: str,
    detections: list[Detection],
    structural: list[dict],
    stats: dict,
) -> str:
    """格式化为可读的标注报告"""
    parts = []

    # 总分
    score = stats['ai_score']
    label = '💀 纯 AI'
    for threshold, desc in AI_SCORE_LABELS:
        if score <= threshold:
            label = desc
            break

    parts.append(f'# 去AI味检测报告\n')
    parts.append(f'**AI 味浓度：{score}/100** — {label}')
    parts.append(f'文本长度：{stats["char_count"]} 字 | '
                 f'检出 {stats["total_detections"]} 处短语 + '
                 f'{stats["structural_issues"]} 个结构问题\n')

    # 分类统计
    if stats['category_breakdown']:
        parts.append('## 问题分布\n')
        for cat, count in sorted(stats['category_breakdown'].items(),
                                  key=lambda x: -x[1]):
            label = CATEGORY_LABELS.get(cat, cat)
            parts.append(f'- {label}: {count} 处')
        parts.append('')

    # 逐条标注
    if detections:
        parts.append('## 具体检出\n')
        for d in detections:
            cat_label = CATEGORY_LABELS.get(d.category, d.category)
            sug = ''
            if d.suggestions:
                options = [f'「{s}」' if s else '删除' for s in d.suggestions]
                sug = f' → 建议：{" / ".join(options)}'
            parts.append(
                f'- **L{d.line_no}** `{d.matched_text}` '
                f'{cat_label} — {d.description}{sug}'
            )
        parts.append('')

    # 结构问题
    if structural:
        parts.append('## 结构问题\n')
        for s in structural:
            parts.append(f'- {s["description"]}')
            parts.append(f'  💡 {s["suggestion"]}')
        parts.append('')

    return '\n'.join(parts)


def rewrite(text: str, detections: list[Detection]) -> str:
    """
    自动替换检出的 AI 短语（使用第一个建议）。

    只替换有明确建议的短语，无建议的保留原文并加 TODO 标记。
    """
    lines = text.split('\n')
    # 按行号分组，从后往前替换（避免位移问题）
    by_line: dict[int, list[Detection]] = {}
    for d in detections:
        by_line.setdefault(d.line_no, []).append(d)

    for line_no in sorted(by_line.keys()):
        dets = sorted(by_line[line_no], key=lambda d: -d.col_start)
        line = lines[line_no - 1]
        for d in dets:
            if d.suggestions:
                replacement = d.suggestions[0]  # 用第一个建议
                line = line[:d.col_start] + replacement + line[d.col_end:]
            # 无建议的不动，报告里已经标出来了
        lines[line_no - 1] = line

    return '\n'.join(lines)


# ============================================================
# 5. CLI 入口
# ============================================================

def process_text(text: str, do_rewrite: bool = False) -> str:
    """主处理函数：检测 + 生成报告（或改写版）"""
    detections, structural, stats = detect(text)

    if do_rewrite:
        rewritten = rewrite(text, detections)
        report = format_report(text, detections, structural, stats)
        return f'{report}\n---\n\n# 改写版本\n\n{rewritten}'
    else:
        return format_report(text, detections, structural, stats)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='去AI味后处理管道')
    parser.add_argument('input', help='输入文件路径（用 - 从 stdin 读取）')
    parser.add_argument('-o', '--output', help='输出文件路径（默认 stdout）')
    parser.add_argument('--rewrite', action='store_true',
                        help='输出改写版本（自动替换有建议的短语）')
    args = parser.parse_args()

    # 读取输入
    if args.input == '-':
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding='utf-8')

    result = process_text(text, do_rewrite=args.rewrite)

    # 输出
    if args.output:
        Path(args.output).write_text(result, encoding='utf-8')
        print(f'[deai_writer] 结果已写入 {args.output}')
    else:
        print(result)


if __name__ == '__main__':
    main()

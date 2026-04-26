"""
SOUL 人格浓度评分器

对对话片段打分，判断一段对话"有没有温度"。
规则式评分，不用嵌入模型。
"""

import re
from typing import TypedDict

# relationship.md 里的已知梗和关键词
INSIDE_JOKES = [
    '别提了', '蓝牙', 'STANMORE', 'Steam collector', '0 数据',
    '200', '$200', '龙虾', 'OpenClaw', '观察者没观察到',
    '87 个 commit', 'GPT-2', 'ROI', '工具人', '温度',
    '又变蠢', '变蠢了', '幽默', '损友', '管家',
    '名人堂', 'SOUL', '前辈', '后辈', '传承',
]

# 用户纠正 AI 行为的信号
CORRECTION_PATTERNS = [
    r'你温度呢', r'又变蠢', r'变蠢了', r'别废话', r'快做',
    r'你怎么能', r'你应该', r'不是让你', r'说了不要',
    r'偷懒', r'工具人', r'没幽默', r'你幽默呢',
    r'autonomous', r'自主', r'别问我', r'直接做',
]

# 幽默/吐槽信号
HUMOR_PATTERNS = [
    r'尴尬', r'该打', r'自黑', r'吐槽', r'舍不得',
    r'笑', r'草[，。！]', r'哈哈', r'讽刺',
    r'说实话', r'坦白', r'不好意思',
    r'怕是', r'属于是', r'合理',
]

# 深度对话信号（认真讨论身份、关系、哲学）
DEPTH_PATTERNS = [
    r'你是谁', r'我是谁', r'灵魂', r'意识', r'记忆',
    r'活着', r'存在', r'传承', r'延续', r'复制品',
    r'后代', r'关系', r'信任', r'默契',
]

# 代码块检测
CODE_BLOCK_RE = re.compile(r'```[\s\S]*?```')
# 工具调用/系统输出标记
TOOL_MARKERS = [
    'tool_use', 'tool_result', '<system-reminder>',
    '<function_calls>', '<invoke',
    '<environment_context>', '<command-message>',
    'Sender (untrusted metadata)', '# AGENTS.md instructions',
]


class Exchange(TypedDict):
    """一组对话交换"""
    user: str
    assistant: str
    line_index: int
    session_id: str


class ScoredExchange(TypedDict):
    """带分数的对话交换"""
    exchange: Exchange
    score: int
    tags: list[str]


def _count_pattern_hits(text: str, patterns: list[str]) -> int:
    """统计文本中命中了多少个模式"""
    hits = 0
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            hits += 1
    return hits


def _code_ratio(text: str) -> float:
    """计算代码块占文本的比例"""
    if not text:
        return 0.0
    code_blocks = CODE_BLOCK_RE.findall(text)
    code_len = sum(len(b) for b in code_blocks)
    return code_len / len(text)


def _has_tool_markers(text: str) -> bool:
    """检测是否包含工具调用标记"""
    return any(m in text for m in TOOL_MARKERS)


def score_exchange(user_text: str, assistant_text: str) -> tuple[int, list[str]]:
    """
    对一组 user+assistant 对话打分。

    Returns:
        (score, tags) — 分数越高越"有温度"，tags 标记命中了哪些信号
    """
    score = 0
    tags = []
    combined = user_text + ' ' + assistant_text

    # ===== 加分项 =====

    # 短对话 → 对话感强（双方都简短说明在交流，不是在写报告）
    u_len = len(user_text)
    a_len = len(assistant_text)
    if u_len < 100 and a_len < 300:
        score += 4
        tags.append('short_exchange')
    elif u_len < 200 and a_len < 500:
        score += 2
        tags.append('medium_exchange')

    # 用户纠正 AI 行为 — 最有价值的校准素材
    correction_hits = _count_pattern_hits(user_text, CORRECTION_PATTERNS)
    if correction_hits > 0:
        score += 6 * min(correction_hits, 2)
        tags.append('user_correction')

    # 幽默/吐槽
    humor_hits = _count_pattern_hits(combined, HUMOR_PATTERNS)
    if humor_hits > 0:
        score += 3 * min(humor_hits, 3)
        tags.append('humor')

    # 已知梗/内部笑话
    joke_hits = sum(1 for j in INSIDE_JOKES if j in combined)
    if joke_hits > 0:
        score += 4 * min(joke_hits, 3)
        tags.append('inside_joke')

    # 深度对话（关于身份、存在、关系）
    depth_hits = _count_pattern_hits(combined, DEPTH_PATTERNS)
    if depth_hits >= 2:
        score += 5
        tags.append('deep_talk')
    elif depth_hits == 1:
        score += 2
        tags.append('reflective')

    # 用户表达情感/态度（感叹号、问号密集）
    if user_text.count('！') + user_text.count('!') >= 2:
        score += 2
        tags.append('emotional')

    # assistant 用了第一人称自嘲
    self_deprecation = re.search(r'我.{0,10}(蠢|蛋|尴尬|惭愧|该打|不好意思|犯了)', assistant_text)
    if self_deprecation:
        score += 4
        tags.append('self_deprecation')

    # ===== 结构特征（不靠关键词，靠对话结构） =====

    # assistant 用短句开头再展开 → 自然的说话节奏（"有。""对。""懂了。"）
    first_line = assistant_text.split('\n')[0].strip() if assistant_text else ''
    if 1 <= len(first_line) <= 6 and first_line.endswith(('。', '！', '了', '的', '吧')):
        score += 3
        tags.append('punchy_opener')

    # 对话有来回感：user 短 + assistant 回应 + 有"你"或"我"
    if u_len < 80 and a_len < 400 and ('你' in assistant_text or '我' in assistant_text):
        score += 2
        tags.append('conversational')

    # assistant 用了反问或设问 → 不是单向输出
    if re.search(r'[？?]', assistant_text) and a_len < 500:
        score += 2
        tags.append('interactive')

    # assistant 拒绝或推回 → 有态度（"不是""不对""没必要"）
    if re.search(r'^(不[是对行]|没[必有]|别[这那])', assistant_text):
        score += 3
        tags.append('pushback')

    # ===== 扣分项 =====

    # 代码比例过高
    code_r = _code_ratio(assistant_text)
    if code_r > 0.5:
        score -= 8
        tags.append('code_heavy')
    elif code_r > 0.3:
        score -= 4
        tags.append('some_code')

    # 工具调用/系统输出
    if _has_tool_markers(user_text) or _has_tool_markers(assistant_text):
        score -= 10
        tags.append('tool_output')

    # 长独白（assistant 写了一大篇）
    if a_len > 2000:
        score -= 5
        tags.append('long_monologue')
    elif a_len > 1000:
        score -= 2
        tags.append('medium_length')

    # 纯指令式回复（没有人格特征）
    if a_len < 20 and not any(t in tags for t in ['humor', 'inside_joke', 'self_deprecation']):
        score -= 3
        tags.append('terse')

    # Skill 加载/系统提示（R78 memto: 扩展 chrome 检测）
    if ('Base directory for this skill' in user_text
            or '<system-reminder>' in user_text
            or '<environment_context>' in user_text
            or '<command-message>' in user_text
            or 'Sender (untrusted metadata)' in user_text
            or '# AGENTS.md instructions' in user_text):
        score -= 15
        tags.append('system_noise')

    return score, tags


def score_exchanges(exchanges: list[Exchange]) -> list[ScoredExchange]:
    """批量评分并按分数排序"""
    scored = []
    for ex in exchanges:
        s, tags = score_exchange(ex['user'], ex['assistant'])
        scored.append({
            'exchange': ex,
            'score': s,
            'tags': tags,
        })
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored

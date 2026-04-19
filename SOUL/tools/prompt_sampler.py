"""
Prompt 采样策略模块（R78 memto 偷点）

7 种策略，首尾锁定（head-and-tail 前 2 后 2），
供 memory_synthesizer / compact 模板 / subagent 派发时使用。
"""
from typing import Literal

SamplingStrategy = Literal[
    'all', 'none', 'first-n', 'last-n',
    'head-and-tail', 'every-nth', 'evenly-spaced',
]


def sample_prompts(
    prompts: list[str],
    strategy: SamplingStrategy = 'head-and-tail',
    n: int = 4,
    nth: int = 3,
) -> list[str]:
    """
    从 prompts 列表中按策略采样。

    Args:
        prompts: 原始 prompt 列表（按时间排序，最旧在前）
        strategy: 采样策略
        n: first-n / last-n 取几条；head-and-tail 时前后各取 n//2 条（默认 n=4 → 前2后2）
        nth: every-nth 的步长

    Returns:
        采样后的 prompt 列表，保持原始顺序
    """
    if not prompts:
        return []

    if strategy == 'all':
        return list(prompts)

    if strategy == 'none':
        return []

    if strategy == 'first-n':
        return list(prompts[:n])

    if strategy == 'last-n':
        return list(prompts[-n:])

    if strategy == 'head-and-tail':
        half = max(1, n // 2)
        if len(prompts) <= n:
            return list(prompts)
        head = list(prompts[:half])
        tail = list(prompts[-half:])
        overlap_start = len(prompts) - half
        if overlap_start < half:
            return list(prompts)
        return head + tail

    if strategy == 'every-nth':
        return [p for i, p in enumerate(prompts) if i % nth == 0]

    if strategy == 'evenly-spaced':
        if len(prompts) <= n:
            return list(prompts)
        step = (len(prompts) - 1) / (n - 1)
        indices = {round(i * step) for i in range(n)}
        return [prompts[i] for i in sorted(indices)]

    raise ValueError(f'Unknown strategy: {strategy}')

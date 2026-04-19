"""
Subprocess spawn 工具（R78 memto 偷点）

auto-scaled timeout: 120s 基准 + 1s/MB，
用于将来调用外部 CLI（如 claude -p）时根据 session 文件大小自动扩展超时。
"""
import os
from pathlib import Path


def scaled_timeout_ms(session_path: str | Path) -> int:
    """
    根据 session 文件大小计算超时毫秒数。

    公式（来自 memto）: max(120_000, 120_000 + mb * 1_000)
    即基准 120s，每 MB 额外加 1s。

    Args:
        session_path: session 文件路径（用于读取文件大小）

    Returns:
        超时毫秒数（int）

    Example:
        >>> scaled_timeout_ms('/path/to/session.jsonl')  # 50MB 文件
        170000  # 120s + 50s = 170s = 170_000ms
    """
    try:
        size_bytes = os.path.getsize(session_path)
        mb = size_bytes / (1024 * 1024)
    except (OSError, FileNotFoundError):
        mb = 0.0
    return max(120_000, int(120_000 + mb * 1_000))


def scaled_timeout_s(session_path: str | Path) -> float:
    """同上，返回秒数（供 subprocess.run timeout= 参数使用）"""
    return scaled_timeout_ms(session_path) / 1000.0

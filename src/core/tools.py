"""
Agent 可以主动调用的系统探测工具，避免问用户能自动获取的信息。
"""
import os
import sys
import subprocess
from pathlib import Path


def get_system_info() -> dict:
    """获取操作系统、Python 版本等基础信息"""
    return {
        "os": {"nt": "Windows", "posix": "Linux/macOS"}.get(os.name, os.name),
        "os_version": os.environ.get("OS", "unknown"),
        "os_release": sys.platform,
        "python": sys.version.split()[0],
        "home": str(Path.home()),
        "username": os.environ.get("USERNAME") or os.environ.get("USER", "unknown"),
    }


def detect_browsers() -> dict:
    """检测已安装的浏览器及其历史路径"""
    home = Path.home()
    found = {}

    candidates = {
        "chrome": [
            home / "AppData/Local/Google/Chrome/User Data/Default/History",
            home / ".config/google-chrome/Default/History",
            home / "Library/Application Support/Google/Chrome/Default/History",
        ],
        "edge": [
            home / "AppData/Local/Microsoft/Edge/User Data/Default/History",
        ],
        "firefox": [
            home / "AppData/Roaming/Mozilla/Firefox/Profiles",
            home / ".mozilla/firefox",
        ],
    }

    for browser, paths in candidates.items():
        for p in paths:
            if p.exists():
                found[browser] = str(p)
                break

    return found


def detect_git_repos(search_paths: list = None) -> list:
    """扫描常用目录找 Git 仓库"""
    home = Path.home()
    if search_paths is None:
        search_paths = [
            home / "Desktop",
            home / "Documents",
            home / "Projects",
            home / "Code",
            home / "dev",
            Path("D:/"),
            Path("C:/Users") / os.environ.get("USERNAME", ""),
        ]

    repos = []
    for base in search_paths:
        if not base.exists():
            continue
        try:
            for item in base.iterdir():
                if item.is_dir() and (item / ".git").exists():
                    repos.append(str(item))
        except PermissionError:
            continue
    return repos[:20]  # 最多返回 20 个


def detect_steam() -> dict:
    """检测 Steam 安装和游戏库"""
    candidates = [
        Path("C:/Program Files (x86)/Steam"),
        Path("C:/Program Files/Steam"),
        Path.home() / ".steam/steam",
        Path.home() / "Library/Application Support/Steam",
    ]

    for p in candidates:
        if p.exists():
            userdata = p / "userdata"
            return {
                "installed": True,
                "path": str(p),
                "userdata": str(userdata) if userdata.exists() else None,
            }

    return {"installed": False}


def detect_claude_sessions() -> dict:
    """找 .claude 目录和会话记录"""
    home = Path.home()
    claude_dir = home / ".claude"
    found = {"claude_dir": str(claude_dir), "exists": claude_dir.exists(), "projects": []}

    if claude_dir.exists():
        projects_dir = claude_dir / "projects"
        if projects_dir.exists():
            found["projects"] = [str(p) for p in projects_dir.iterdir() if p.is_dir()][:10]

    return found


# 供 agent 调用的工具定义（Anthropic tool schema）
SYSTEM_TOOLS = [
    {
        "name": "get_system_info",
        "description": "获取操作系统、用户名等基础系统信息",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "detect_browsers",
        "description": "检测本机已安装的浏览器及其历史数据库路径",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "detect_git_repos",
        "description": "扫描本机常用目录，找出存在的 Git 仓库列表",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "detect_steam",
        "description": "检测 Steam 是否安装及游戏库路径",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "detect_claude_sessions",
        "description": "找出 .claude 目录和 Claude 会话记录位置",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

TOOL_HANDLERS = {
    "get_system_info": get_system_info,
    "detect_browsers": detect_browsers,
    "detect_git_repos": detect_git_repos,
    "detect_steam": detect_steam,
    "detect_claude_sessions": detect_claude_sessions,
}

CLARIFY_TOOL = {
    "name": "clarify",
    "description": "评估问题清晰度。若不清晰，按类型追问；若清晰，输出正式定义。调用此工具将中断当前执行流程。",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_clear": {
                "type": "boolean",
                "description": "问题是否已经足够清晰，可以直接执行"
            },
            "clarification_type": {
                "type": "string",
                "enum": [
                    "missing_info",
                    "ambiguous_requirement",
                    "approach_choice",
                    "risk_confirmation",
                    "suggestion"
                ],
                "description": (
                    "澄清类型（优先级排序）："
                    "missing_info=缺少必要信息, "
                    "ambiguous_requirement=需求有多种解读, "
                    "approach_choice=需要用户选择方案, "
                    "risk_confirmation=高风险操作需确认, "
                    "suggestion=有更好的替代方案"
                )
            },
            "question": {
                "type": "string",
                "description": "若不清晰，向用户提出的下一个问题（只问一个，且只问工具无法自动获取的主观信息）"
            },
            "definition": {
                "type": "string",
                "description": "若清晰，给出简洁的问题定义（一句话）"
            },
            "clarity_level": {
                "type": "string",
                "enum": ["低", "中", "高"],
                "description": "当前问题的清晰程度"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键词标签列表"
            }
        },
        "required": ["is_clear", "clarity_level", "tags"]
    }
}

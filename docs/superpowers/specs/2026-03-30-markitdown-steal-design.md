# MarkItDown 偷师：智能文档转换

> 日期: 2026-03-30
> 偷师对象: [microsoft/markitdown](https://github.com/microsoft/markitdown)
> 范围: 全局 skill 升级 + Orchestrator 集成

## 偷师成果

从 MarkItDown 提炼的 8 个可偷模式：

| # | 模式 | 原理 | 落地位置 |
|---|---|---|---|
| A | Magika 多轮猜测 | 文件名推断 + 内容检测同时跑 | convert.sh 格式检测 |
| B | 优先级覆盖插件 | `priority` float 无感替换 built-in | 未来 Governance capability |
| C | 延迟依赖报错 | 模块顶层 try/except，调用时才 raise | media.py extract 函数 |
| D | HTML 中间格式 | DOCX/XLSX/PPTX → HTML → Markdown | markitdown 内部已实现 |
| E | ZIP 递归自引用 | 构造注入 self，递归走主管线 | markitdown 内部已实现 |
| F | 流位置不变量 | accepts() 后 assert 位置不变 | 设计参考 |
| G | Accept Header 协商 | `text/markdown` 优先拿 agent-friendly 格式 | convert.sh URL 处理 |
| H | exiftool 路径白名单 | which() 后检查目录安全 | 设计参考 |

本轮实施：**A, C, G** + 后处理管线。

## 一、全局 Skill 升级

### 目标

将 `~/.claude/skills/markdown-converter/` 从速查卡升级为智能转换调度器。

### 文件结构

```
~/.claude/skills/markdown-converter/
├── SKILL.md          # 智能调度逻辑 + 后处理指令
└── convert.sh        # 格式检测 → markitdown → 后处理
```

### SKILL.md 设计

触发条件：用户提到文件转换、PDF/DOCX/PPTX/XLSX 处理、"转成 markdown"。

核心逻辑：
1. 检测输入类型（文件路径 / URL / stdin）
2. 如果是 URL → 先尝试 `Accept: text/markdown` 直接获取（模式 G）
3. 如果是文件 → `file --mime-type` + 扩展名双重验证（模式 A 简化版）
4. 调用 `uvx markitdown` 转换
5. 后处理管线清洗输出

### convert.sh 设计

```bash
# 输入：文件路径或 URL
# 输出：清洗后的 markdown（stdout 或 -o 文件）
#
# 后处理管线：
# 1. 连续 3+ 空行 → 2 空行
# 2. 去除重复页眉/页脚（相同文本在 3+ 页出现）
# 3. 超长表格截断（>50 行保留前 20 行 + 摘要）
# 4. 可选 --max-tokens N 按 token 预算截断
```

### 后处理规则

| 规则 | 触发条件 | 处理 |
|------|----------|------|
| 空行压缩 | 3+ 连续空行 | → 2 空行 |
| 页眉/页脚去重 | 相同文本出现 3+ 次且间距均匀 | 删除重复，保留首次 |
| 表格截断 | >50 行 | 前 20 行 + `[... 省略 N 行 ...]` |
| Token 预算 | `--max-tokens` 参数 | 截断 + `[已截断，原文 ~X tokens]` |

## 二、Orchestrator 集成

### 现状

TG bot 收到 PDF → 存磁盘 → LLM 只看到 `"[用户发送了文件: document.pdf]"` → LLM 对文档内容完全失明。

### 方案：handler 层提取（与 voice transcription 对齐）

```
voice:    下载 → whisper 转录 → att.text
document: 下载 → markitdown 提取 → att.text   ← 新增
```

### 改动文件

#### 1. `src/channels/media.py` — 新增 `extract_document_text()`

```python
# 偷模式 C：延迟依赖
_markitdown_available = None  # None = 未检测

def extract_document_text(path: str, mime: str = "") -> str:
    """用 markitdown 提取文档文本。失败返回空字符串，不抛异常。"""
    # 1. 延迟检测 markitdown 可用性
    # 2. MIME 白名单：pdf, docx, pptx, xlsx, xls, html, csv, epub
    # 3. subprocess 调用 uvx markitdown
    # 4. 后处理：空行压缩 + 截断
    # 5. 超时保护：30 秒
```

支持的 MIME 类型白名单：
- `application/pdf`
- `application/vnd.openxmlformats-officedocument.*`（docx/pptx/xlsx）
- `application/vnd.ms-excel`（xls）
- `text/html`
- `text/csv`
- `application/epub+zip`

#### 2. `src/channels/telegram/handler.py` — 接入提取

在 `_download_tg_file()` 返回后、`attachments.append()` 前：

```python
if att and att.media_type == MediaType.FILE:
    att.text = extract_document_text(att.local_path, att.mime_type)
```

#### 3. `src/channels/chat/context.py` — 内联文档文本

对非图片附件，如果 `att.text` 非空：

```python
# 现有：images → base64 内联
# 新增：documents with text → 文本内联
content += f"\n\n📄 {att.file_name}:\n```\n{att.text}\n```"
```

### 依赖策略

- **不加 markitdown 到 requirements.txt**（模式 C）
- Docker 镜像预装 `pipx` / `uvx`，容器内 `uvx markitdown` 可用
- 本地开发环境首次调用自动缓存
- 如果 markitdown 不可用 → log warning → att.text 留空 → 降级为原有行为

## 三、不做的事

- 不自建 converter pipeline（markitdown 已经够好）
- 不做 OCR（需要时用 `-d` Azure Document Intelligence）
- 不做实时 streaming 提取（文件一般不大，同步够用）
- 不存提取结果到独立表（att.text 随消息存 DB 即可）

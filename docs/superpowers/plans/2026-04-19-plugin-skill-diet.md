# Plan: Plugin / Skill 瘦身（基于使用数据）

## Goal

基于 `~/.claude.json` 里的 `skillUsage` + `toolUsage` 真实统计，把 `~/.claude/settings.json` 的 `enabledPlugins` 从 24 条砍到「每条都至少用过一次」的规模，并同时配置 `skillOverrides` 把冷门 skill 静音，使新会话启动时 `/context` 的 skills + MCP 列表减少 ≥50%。

## 前置状态（上一会话结束时）

- 已清理：`context7` / `playwright` / `telegram` 三个 plugin（settings.json + installed_plugins.json + cache 目录）
- 备份位置：`~/.claude/.trash/20260419-mcp-cleanup/`
- 本地保留 MCP：`plugin:chrome-devtools-mcp` 唯一一个
- 云端 MCP（需用户手动去 claude.ai 删）：GoDaddy / Context7 / Excalidraw / Goodnotes —— 不属本计划范围
- `settings.json` 当前 `enabledPlugins` 24 条，名单见该文件 line 90-118

## File Map

- `~/.claude.json` — Read only（读取 `skillUsage`、`toolUsage`）
- `~/.claude/settings.json` — Modify（删 `enabledPlugins` 冷门项；新增 `skillOverrides` 段；可能调 `skillListingMaxDescChars`）
- `~/.claude/plugins/installed_plugins.json` — Modify（同步删掉 settings 里禁用的 plugin）
- `~/.claude/plugins/cache/claude-plugins-official/<plugin>/` — Move to `~/.claude/.trash/20260419-mcp-cleanup/`（每个被禁的 plugin）
- `~/.claude/.trash/20260419-mcp-cleanup/settings.json.before-diet.bak` — Create（本轮修改前的二次备份，区别于上一会话的 settings.json.bak）

## 数据口径约定

- **"冷门"**：`skillUsage[<name>].usageCount < 3` **且** `lastUsedAt` 早于最近 30 天（取 `now - 30d`）
- **"重复"**：同名 skill 在多个 plugin 里都出现（如 `claude-api:canvas-design` 与 `document-skills:canvas-design`），保留使用多的那份
- **"保护名单"**（无论使用数据怎样都不动）：
  - `chrome-devtools-mcp@claude-plugins-official`（上一轮用户明确要保留）
  - `superpowers@claude-plugins-official`（CLAUDE.md 里引用了 superpowers 的 skills）
  - `orchestrator-soul@local-plugins`（本项目自带）
  - `remember@claude-plugins-official`（boot 流程依赖）
  - `commit-commands@claude-plugins-official`（git 工作流依赖）

## Steps

1. 读取 `~/.claude.json`，导出 `skillUsage`、`toolUsage` 两张表到临时 json → verify: `python -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude.json'))); print('skillUsage:', len(d.get('skillUsage',{})), 'toolUsage:', len(d.get('toolUsage',{})))"` 打印出两个非零整数

2. 对 `skillUsage` 按 `usageCount` 降序打印，并标注每个 skill 归属的 plugin（通过匹配 `<plugin>:` 前缀）→ verify: 输出包含至少 20 条 `skill_name  count=N  last=<iso>` 的行，肉眼能识别 top 10

3. 读 `~/.claude/settings.json` 的 `enabledPlugins` 24 个键，按「每个 plugin 下至少一个 skill 被用过 ≥3 次」为标准分成 keep / drop 两组，打印决策表（plugin，决策，依据）→ verify: 表格中每行有明确的 keep/drop 标签，drop 组 ≥5 条，keep 组 ≥ 保护名单 5 个

4. 把决策表存到 `~/.claude/.trash/20260419-mcp-cleanup/diet-decisions.md` 供事后审计 → verify: `ls ~/.claude/.trash/20260419-mcp-cleanup/diet-decisions.md` 非空，文件末尾有"生成时间：<timestamp>"
   - depends on: step 3

5. 备份 `~/.claude/settings.json` 到 `~/.claude/.trash/20260419-mcp-cleanup/settings.json.before-diet.bak` → verify: `diff ~/.claude/settings.json ~/.claude/.trash/20260419-mcp-cleanup/settings.json.before-diet.bak` 输出为空（二者相同）

6. 用 Python 读 `~/.claude/settings.json`，从 `enabledPlugins` 中删除 step 3 drop 组的每一项，写回（保持 2 空格缩进）→ verify: `python -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print(len(d['enabledPlugins']))"` 输出 ≤ `24 - len(drop)` 且等于 `24 - len(drop)`
   - depends on: step 5

7. 同步修改 `~/.claude/plugins/installed_plugins.json`，对每一个 drop 项执行 `del data['plugins'][key]` 写回 → verify: `python -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json'))); print(len(d['plugins']))"` 数量减少 = `len(drop)`
   - depends on: step 6

8. 把 drop 组每个 plugin 的 cache 目录 `~/.claude/plugins/cache/claude-plugins-official/<plugin>/` 挪到 `~/.claude/.trash/20260419-mcp-cleanup/<plugin>/`（若 trash 下已有同名目录，追加 `-v2` 后缀）→ verify: `ls ~/.claude/plugins/cache/claude-plugins-official/ | grep -E '^(context7|playwright|telegram)$'` 无输出（上轮和本轮 drop 的 plugin 都不在 cache 里）
   - depends on: step 7

9. 在 `~/.claude/settings.json` 顶层加 `"skillListingMaxDescChars": 400`（从默认 1536 降到 400）→ verify: `python -c "import json,os; print(json.load(open(os.path.expanduser('~/.claude/settings.json'))).get('skillListingMaxDescChars'))"` 输出 `400`

10. 在 step 2 的输出中挑出 `usageCount == 0` 且属于保护 plugin 的 skill（即不能整个 plugin 删但个别 skill 没用过），在 `settings.json` 加 `skillOverrides: { "<skill>": "name-only" }` 批量配置 → verify: `python -c "import json,os; print(len(json.load(open(os.path.expanduser('~/.claude/settings.json'))).get('skillOverrides', {})))"` 输出 ≥5
    - depends on: step 9

11. 在新 shell 里运行 `claude mcp list` 和启动一个一次性 `claude --print "/context"` 会话（若 CLI 支持），对比启动前后的 MCP 条目数与 skills 列表长度 → verify: MCP 列表仅剩 `plugin:chrome-devtools-mcp` + 用户未删的云端 MCP；skills 列表行数相比上轮会话启动时减少 ≥50%（目测或 `wc -l`）
    - depends on: step 10

12. 把本轮动作写进 `~/.claude/.trash/20260419-mcp-cleanup/diet-report.md`（内容：drop 了哪些 plugin、静音了哪些 skill、启动前/后 skills 数量对比、恢复指令）→ verify: 文件存在且包含 "Rollback" 小节，给出 `cp settings.json.before-diet.bak ...` 一行可复制的回滚命令
    - depends on: step 11

## 回滚方案

本轮所有破坏性动作都保留原件在 `~/.claude/.trash/20260419-mcp-cleanup/`。任一步出错：

```bash
cp ~/.claude/.trash/20260419-mcp-cleanup/settings.json.before-diet.bak ~/.claude/settings.json
cp ~/.claude/.trash/20260419-mcp-cleanup/installed_plugins.json.bak ~/.claude/plugins/installed_plugins.json
# plugin cache 目录从 .trash/ 挪回 cache/claude-plugins-official/（如需要）
```

## 非目标（明确不做）

- 不动云端 4 个 `claude.ai` MCP —— CLI 管不了，需用户自己去 https://claude.ai/settings/connectors 删
- 不卸载 marketplace 源（`extraKnownMarketplaces` 保持不变，删 plugin 不删市场，保留重装可能性）
- 不修改 `permissions` / `hooks` / `env` —— 只动 plugin / skill 相关字段
- 不改项目级 `.claude/settings.json`，只动全局 `~/.claude/settings.json`

## 下一会话开场白

> 上一会话删了 3 个 plugin（context7/playwright/telegram），现在要基于 skillUsage 数据继续瘦身。读 `docs/superpowers/plans/2026-04-19-plugin-skill-diet.md`，从 Step 1 开始执行，每做完一步打勾给我看。

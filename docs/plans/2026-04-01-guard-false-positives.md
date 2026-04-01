# Plan: Guard Hook False Positive Fix

> Date: 2026-04-01
> Trigger: `git commit -m "...session..."` blocked by `browser-cookie-access` rule
> Priority: P1 (blocks normal workflow)

## Problem

Rule 9 (`browser-cookie-access`) in both `guard-redflags.sh:112-117` and `exec-policy.yaml:68-75`:

```yaml
match_all:
  - pattern: "(Cookies|Login\\s*Data|Session|\\.cookie)"  # ← "Session" 太宽
    flags: "i"
  - pattern: "(sqlite3|cat|cp|curl)"                       # ← "cat" 命中 HEREDOC
    flags: "i"
```

`git commit -m "$(cat <<'EOF' ... session ... EOF)"` 同时命中两个条件：
- `Session` (commit message 里的正常词)
- `cat` (HEREDOC 语法)

## Root Cause

`Session` 作为独立词太泛——出现在 commit message、文件名、变量名中极其常见。原意是防止 `sqlite3 ~/.config/chromium/.../Cookies` 之类的 browser session theft，但 pattern 没约束上下文。

## File Map

| File | Change |
|------|--------|
| `config/exec-policy.yaml` | 收窄 Rule 9 patterns |
| `.claude/hooks/guard-redflags.sh` | 同步收窄 bash fallback |

## Steps

### Step 1: 收窄 session/cookie 匹配 — exec-policy.yaml
> depends on: none
> verify: `python3 scripts/exec_policy_loader.py` 不 block `git commit -m "feat: session boundary"`

将 `Session` 改为 browser-specific 路径模式：

```yaml
- name: browser-cookie-access
  action: block
  description: "Browser cookie/session/credential file access"
  match_all:
    - pattern: "(Cookies|Login\\s*Data|Session\\s*Storage|\\.cookie|Cookie\\s*Store)"
      flags: "i"
    - pattern: "(sqlite3|cp\\s|curl)"
      flags: "i"
  exclude:
    - pattern: "git\\s+(commit|log|diff|show|push|pull|merge|rebase|checkout|branch)"
```

改动点：
1. `Session` → `Session\\s*Storage` — 只匹配 browser 的 "Session Storage"，不匹配普通英文词
2. `cat` 从第二个 pattern 移除 — HEREDOC 的 `cat` 不是数据读取工具
3. 加 `exclude` 白名单 — git 操作永远不是 cookie theft

### Step 2: 同步 bash fallback — guard-redflags.sh
> depends on: Step 1
> verify: `echo 'git commit -m "session boundary"' | grep` 测试不命中

```bash
# Rule 9 — browser-cookie-access (narrowed)
if echo "$COMMAND" | grep -qiE '(Cookies|Login\s*Data|Session\s*Storage|\.cookie|Cookie\s*Store)' && \
   echo "$COMMAND" | grep -qiE '(sqlite3|cp\s|curl)' && \
   ! echo "$COMMAND" | grep -qE 'git\s+(commit|log|diff|show|push|pull)'; then
```

### Step 3: 回归测试 — 确认既能放行也能拦截
> depends on: Step 2
> verify: 4 case 全过

| Case | Expected | Pattern |
|------|----------|---------|
| `git commit -m "feat: session boundary"` | ✅ allow | git exclude |
| `sqlite3 ~/.config/chromium/Default/Cookies` | ❌ block | Cookies + sqlite3 |
| `cp ~/Library/Cookies/Cookies.binarycookies /tmp/` | ❌ block | Cookies + cp |
| `cat Session\ Storage/some-file` | ❌ block | Session Storage + cat |

### Step 4: 审计其他规则的误报风险
> depends on: Step 3
> verify: 列出所有宽泛 pattern 并评估

扫描所有规则中的单词级匹配（没有 `\b` 或路径约束的），标记潜在误报：
- Rule 10 `interpreter-injection`: `curl|wget` 在 python -c 里 — 可能误报 `python3 -c "print('curl')"` 但实际风险低
- Rule 5 `sudo`: `\bsudo\b` 加了 word boundary，安全
- 重点关注 Rule 9 同类问题：pattern 过宽 + 第二个条件匹配到 shell 语法而非实际操作

## Verification

最终验证：在修复后的环境中执行：
```bash
git commit -m "$(cat <<'EOF'
feat(hooks): session boundary detection
EOF
)"
```
必须成功，不被 block。

# Claude Code Hooks 事件系统深层逆向

> **Round 34** | 偷师目标：Claude Code Hook 生命周期、事件分类学、执行模型
> **分支**: `steal/claude-code-deep-infra`
> **日期**: 2026-04-01
> **来源**: [官方 Hooks 文档](https://code.claude.com/docs/en/hooks) + [anthropics/claude-code hook-development SKILL](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md) + [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery) + [SmartScope 完整指南](https://smartscope.blog/en/generative-ai/claude/claude-code-hooks-guide/) + [Steve Kinney 教程](https://stevekinney.com/courses/ai-development/claude-code-hook-examples) + [DataCamp 实战指南](https://www.datacamp.com/tutorial/claude-code-hooks)

---

## 一、事件分类学：21 个生命周期事件全表

截至 2026 年 4 月，Claude Code 的 Hook 系统从最初的 ~7 个事件扩展到 **21 个**。按生命周期阶段分组：

### 1.1 会话生命周期（Session Lifecycle）

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **Setup** | 仓库初始化 / 周期性维护 | 否 | Command |
| **SessionStart** | 新会话启动 / 恢复 / 清除 | 否 | Command only |
| **SessionEnd** | 会话终止（exit / SIGINT / error） | 否 | Command |

### 1.2 用户输入层

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **UserPromptSubmit** | 用户提交 prompt，在 Claude 处理前 | **是**（exit 2 / decision:block） | Prompt, Command |

### 1.3 工具执行层（Tool Lifecycle）

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **PreToolUse** | 工具参数生成后、执行前 | **是**（deny / ask） | Prompt, Command, Agent |
| **PermissionRequest** | 权限对话框即将弹出时 | **是**（allow / deny） | Command |
| **PostToolUse** | 工具成功执行后 | 否（已执行） | Prompt, Command |
| **PostToolUseFailure** | 工具执行失败后 | 否 | Command |

### 1.4 停止与完成层

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **Stop** | Claude 认为自己完成了 | **是**（exit 2 = 继续工作） | Prompt, Command |
| **StopFailure** | API 错误导致中断（限流 / 认证失败等） | 否 | Command |
| **Notification** | 系统通知 | 否 | Command |

### 1.5 子代理层（Subagent Orchestration）

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **SubagentStart** | 子代理被生成 | 否 | Command |
| **SubagentStop** | 子代理完成 | **是**（exit 2 阻止完成） | Prompt, Command |

### 1.6 多代理协作层（Multi-Agent / Team）

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **TaskCreated** | 共享任务列表中创建任务 | **是** | Command |
| **TaskCompleted** | 任务完成 | **是** | Command |
| **TeammateIdle** | 团队成员进入空闲 | **是** | Command |

### 1.7 维护与配置层

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **PreCompact** | 上下文压缩前 | 否 | Command |
| **ConfigChange** | 配置文件变更 | **是**（decision:block） | Command |
| **FileChanged** | 监视文件磁盘变更 | 否 | Command |
| **InstructionsLoaded** | CLAUDE.md 等指令文件加载 | 否 | Command |

### 1.8 交互与工作树层

| 事件 | 触发时机 | 可阻断？ | Handler 类型 |
|------|---------|---------|-------------|
| **Elicitation** | MCP 询问用户 | **是**（accept/decline/cancel） | Command |
| **ElicitationResult** | 询问结果返回 | **是** | Command |
| **WorktreeCreate** | 工作树创建 | 否（返回路径） | Command |
| **WorktreeRemove** | 工作树删除 | 否 | Command |
| **CwdChanged** | 工作目录切换 | 否 | Command |

**关键发现**：21 个事件中有 **11 个可阻断**（PreToolUse / PermissionRequest / UserPromptSubmit / Stop / SubagentStop / TaskCreated / TaskCompleted / TeammateIdle / ConfigChange / Elicitation / ElicitationResult）。这是一个完整的控制平面。

---

## 二、输入 Schema 详解

### 2.1 公共字段（所有事件）

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/dir",
  "permission_mode": "default|plan|acceptEdits|auto|dontAsk|bypassPermissions",
  "hook_event_name": "EventName"
}
```

子代理事件额外包含：
```json
{
  "agent_id": "agent-unique-id",
  "agent_type": "Explore|Bash|Plan|CustomAgentName"
}
```

### 2.2 工具事件（PreToolUse / PostToolUse / PostToolUseFailure）

```json
{
  "tool_name": "Bash|Write|Edit|Read|Glob|Grep|Agent|mcp__server__tool",
  "tool_input": {
    "command": "npm test",           // Bash
    "file_path": "/path/to/file",   // Read/Write/Edit
    "pattern": "**/*.ts",           // Glob/Grep
    "prompt": "...",                // Agent
    "description": "...",
    "timeout": 120000
  },
  "tool_use_id": "toolu_01ABC123...",
  "tool_response": { ... },         // PostToolUse only
  "error": "error message",         // PostToolUseFailure only
  "is_interrupt": false              // PostToolUseFailure only
}
```

### 2.3 SessionStart

```json
{
  "source": "startup|resume|clear|compact",
  "model": "claude-sonnet-4-6"
}
```

特殊能力：可通过 `$CLAUDE_ENV_FILE` 持久化环境变量：
```bash
echo "export PROJECT_TYPE=nodejs" >> "$CLAUDE_ENV_FILE"
```

### 2.4 Stop / SubagentStop

```json
{
  "stop_hook_active": false,
  "last_assistant_message": "Claude 的最终回复文本",
  "agent_transcript_path": "/path/..."  // SubagentStop only
}
```

### 2.5 StopFailure

```json
{
  "error": "rate_limit|authentication_failed|billing_error|invalid_request|server_error|max_output_tokens|unknown",
  "error_details": "additional details",
  "last_assistant_message": "API Error: ..."
}
```

### 2.6 PermissionRequest

```json
{
  "tool_name": "Bash",
  "tool_input": { "command": "rm -rf /" },
  "permission_suggestions": [
    {
      "type": "addRules",
      "rules": [{"toolName": "Bash", "ruleContent": "rm -rf /"}],
      "behavior": "allow",
      "destination": "localSettings"
    }
  ]
}
```

### 2.7 多代理事件

```json
// TaskCreated / TaskCompleted
{
  "task_id": "task-001",
  "task_subject": "Implement feature",
  "task_description": "...",
  "teammate_name": "researcher",
  "team_name": "my-project"
}

// TeammateIdle
{
  "teammate_name": "researcher",
  "team_name": "my-project"
}
```

### 2.8 InstructionsLoaded

```json
{
  "file_path": "/path/to/CLAUDE.md",
  "memory_type": "User|Project|Local|Managed",
  "load_reason": "session_start|nested_traversal|path_glob_match|include|compact",
  "globs": ["path/glob/*.md"],
  "trigger_file_path": "/path/accessed",
  "parent_file_path": "/parent/file"
}
```

---

## 三、输出 Schema 与控制流

### 3.1 通用字段

```json
{
  "continue": true,              // false = 整个 Claude 停止
  "stopReason": "message",       // continue:false 时显示
  "suppressOutput": false,       // 隐藏详细输出
  "systemMessage": "warning"     // 注入到 Claude 上下文的消息
}
```

### 3.2 PreToolUse 决策（hookSpecificOutput 模式）

这是 **唯一使用嵌套决策模式** 的事件：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny|ask",
    "permissionDecisionReason": "explanation",
    "updatedInput": {
      "command": "modified command",
      "timeout": 120000
    },
    "additionalContext": "context for Claude"
  }
}
```

三种决策的效果：

| 决策 | 效果 | reason 展示给谁 |
|------|------|---------------|
| `allow` | 跳过权限弹窗，直接执行 | 用户 |
| `deny` | 阻止工具调用，错误反馈 | Claude（不给用户看） |
| `ask` | 弹出权限对话框 | 对话框上方 |

**重要**：`allow` 不能覆盖用户已配置的 deny 规则。它只跳过弹窗。

### 3.3 updatedInput — 工具输入修改

**可用事件**：PreToolUse、PermissionRequest
**不可用**：PostToolUse、PostToolUseFailure

`updatedInput` **完全替换**原始输入对象。必须包含所有未修改的字段。

用例：
1. **安全沙箱**：给命令加 `--dry-run`
2. **自动审批 + 修改**：允许执行但去掉危险 flag
3. **Headless 模式**：自动填充 AskUserQuestion 的 answers

### 3.4 其他事件的 Top-Level Decision

```json
// Stop / SubagentStop / UserPromptSubmit / ConfigChange
{
  "decision": "block",
  "reason": "why"
}
```

### 3.5 Exit Code 语义

| Exit Code | 含义 | stdout | stderr |
|-----------|------|--------|--------|
| **0** | 成功 | JSON 被解析为决策 | 忽略 |
| **2** | 阻断错误 | **被忽略** | 反馈给 Claude/用户 |
| **其他** | 非阻断错误 | 忽略 | 仅 verbose 模式显示 |

---

## 四、执行模型

### 4.1 四种 Handler 类型

| 类型 | 描述 | 适用场景 |
|------|------|---------|
| **command** | 执行 shell 命令，stdin 接收 JSON | 确定性检查、文件操作、外部工具 |
| **http** | POST JSON 到 URL | Webhook、远程服务集成 |
| **prompt** | 发送 prompt 到轻量 Claude 模型（默认 Haiku） | 上下文感知的语义决策 |
| **agent** | 生成子代理，可使用 Read/Grep/Glob 工具 | 深度验证（如检查测试覆盖） |

### 4.2 并行执行

**同一事件的所有匹配 hook 并行执行**。没有顺序保证。

去重规则：
- Command hooks：按命令字符串去重
- HTTP hooks：按 URL 去重
- 其他：不去重

决策合并：
- 任意 hook 返回 `continue: false` → Claude 停止
- 任意 hook 返回阻断决策 → 操作被阻断
- 其他情况：所有输出累积

### 4.3 Async 模式

```json
{
  "type": "command",
  "command": "bash log.sh",
  "async": true
}
```

异步 hook 在后台运行，结果被忽略。适用于日志、通知等纯副作用操作。

### 4.4 超时模型

| Handler 类型 | 默认超时 | 可配置 |
|-------------|---------|--------|
| Command | 600s | `"timeout": N` |
| HTTP | 30s | 是 |
| Prompt | 30s | 是 |
| Agent | 60s | 是 |

超时行为：
- 非阻断错误（执行继续）
- 进程被 kill
- 仅 verbose 模式可见
- **不会阻断操作**

### 4.5 错误处理

- Hook 崩溃 → 非阻断错误，执行继续
- JSON 解析失败 → verbose 模式显示，不应用决策
- 缺少字段 → 使用默认值（如 `continue` 默认 `true`）
- 常见坑：shell profile 启动时输出文本，干扰 JSON 解析

---

## 五、配置系统

### 5.1 Hook 来源层级（优先级从高到低）

1. **Managed policy**（企业级）— 最高优先级
2. **Plugin hooks**（启用的插件）
3. **Project hooks**（`.claude/settings.json`）— 可提交到 repo
4. **Local hooks**（`.claude/settings.local.json`）— gitignored
5. **User hooks**（`~/.claude/settings.json`）— 机器级别

所有来源的 hooks **合并执行**，不是覆盖。

企业控制：`allowManagedHooksOnly` 可禁用所有非企业 hooks。

### 5.2 settings.json 格式

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/guard.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### 5.3 Plugin hooks.json 格式

```json
{
  "description": "Safety hooks",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Validate file write safety...",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

### 5.4 Matcher 语法

```
"Bash"                    // 精确匹配
"Read|Write|Edit"         // 多工具
"*"                       // 通配
"mcp__.*"                 // 所有 MCP 工具（正则）
"mcp__plugin_asana_.*"    // 特定插件的 MCP 工具
```

大小写敏感。

### 5.5 环境变量

| 变量 | 可用范围 | 描述 |
|------|---------|------|
| `$CLAUDE_PROJECT_DIR` | 所有 command hooks | 项目根路径 |
| `$CLAUDE_PLUGIN_ROOT` | 插件 hooks | 插件目录路径 |
| `$CLAUDE_ENV_FILE` | SessionStart only | 写入持久化环境变量 |
| `$CLAUDE_CODE_REMOTE` | 所有 | 是否远程运行 |

---

## 六、高级模式

### 6.1 Prompt Hook 模式（LLM 驱动决策）

```json
{
  "type": "prompt",
  "prompt": "Evaluate if this Bash command is safe: $TOOL_INPUT. Consider: destructive ops, network access, privilege escalation. Return 'approve' or 'deny' with reason."
}
```

优势：上下文感知、边界情况处理好、易维护。
劣势：延迟（需要 API 调用）、不确定性。

### 6.2 Agent Hook 模式（多轮验证）

```json
{
  "type": "agent",
  "prompt": "Verify that all modified files have corresponding test files. Use Read and Grep to check.",
  "timeout": 60
}
```

适用于需要读代码才能判断的深度验证。

### 6.3 PermissionRequest 自动审批

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedPermissions": [
        {
          "type": "addRules",
          "rules": [{"toolName": "Bash", "ruleContent": "npm run"}],
          "behavior": "allow",
          "destination": "projectSettings"
        }
      ]
    }
  }
}
```

这让 hook 能够等价于用户点击 "Always allow"。

### 6.4 Stop Hook 强制继续

```json
{
  "Stop": [
    {
      "hooks": [
        {
          "type": "prompt",
          "prompt": "Check if all acceptance criteria are met: tests pass, build succeeds, code formatted. If not, return 'block' with what's missing."
        }
      ]
    }
  ]
}
```

**这是 Orchestrator 没有的杀手级功能**：用 LLM 判断任务是否真的完成。

### 6.5 ConfigChange 安全审计

```json
{
  "ConfigChange": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "bash audit-config-change.sh",
          "timeout": 5
        }
      ]
    }
  ]
}
```

企业级：任何配置变更都可以被拦截和审计。

### 6.6 StopFailure 韧性处理

```json
{
  "StopFailure": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "bash alert-on-failure.sh"
        }
      ]
    }
  ]
}
```

处理限流、认证失败等 API 错误，发送告警或自动重试。

---

## 七、与 Orchestrator 对比分析

### 7.1 Orchestrator 现有 Hook 覆盖

| 事件 | Orchestrator | Claude Code |
|------|-------------|-------------|
| SessionStart | ✅ session-start.sh（编译 boot + 系统状态 + 恢复） | ✅ |
| UserPromptSubmit | ✅ routing-hook.sh + correction-detector.sh | ✅ |
| PreToolUse(Bash) | ✅ guard-ollama-rm + guard-redflags（14 条规则） | ✅ |
| PreToolUse(Edit/Write) | ✅ config-protect.sh（配置松绑检测） | ✅ |
| PreToolUse(Agent) | ✅ dispatch-gate.sh（[STEAL] 分支强制） | ✅ |
| PostToolUse | ✅ persona-anchor + loop-detector | ✅ |
| PostToolUse(Bash) | ✅ error-detector.sh（错误学习） | ✅ |
| Stop | ✅ session-stop.sh（git 安全 + 经历提取 + 记忆审计） | ✅ |
| PreCompact | ✅ pre-compact.sh（快照 + 9 段压缩模板 + 人设锚点） | ✅ |
| **PostToolUseFailure** | ❌ | ✅ |
| **PermissionRequest** | ❌ | ✅ |
| **SubagentStart** | ❌ | ✅ |
| **SubagentStop** | ❌ | ✅ |
| **StopFailure** | ❌ | ✅ |
| **ConfigChange** | ❌ | ✅ |
| **FileChanged** | ❌ | ✅ |
| **SessionEnd** | ❌（Stop 里做了部分） | ✅ |
| **Setup** | ❌ | ✅ |
| **TaskCreated/Completed** | ❌ | ✅ |
| **TeammateIdle** | ❌ | ✅ |
| **InstructionsLoaded** | ❌ | ✅ |

### 7.2 Handler 类型差距

| Handler | Orchestrator | Claude Code |
|---------|-------------|-------------|
| command | ✅（全部用这个） | ✅ |
| http | ❌ | ✅ |
| prompt | ❌ | ✅（LLM 驱动决策） |
| agent | ❌ | ✅（多轮验证） |

**这是最大的结构性差距**：Orchestrator 只用 command hooks（确定性 bash 脚本）。Claude Code 的 prompt/agent hooks 允许用 LLM 做上下文感知的语义决策，处理 bash 正则无法覆盖的边界情况。

---

## 八、可偷模式清单

### P0（高价值，可立即实施）

| # | 模式名 | 来源事件 | 价值 | 实施路径 |
|---|--------|---------|------|---------|
| 1 | **Prompt Hook Gateway** | PreToolUse | 用轻量 LLM（qwen3:1.7b）做语义安全判断，覆盖 bash 正则的盲区 | session-start 检查 Ollama 可用性，PreToolUse 可选走 prompt 路径 |
| 2 | **Stop Completeness Verifier** | Stop | 用 LLM 判断任务是否真正完成（测试跑了没、build 通过没） | Stop hook 加 prompt 判断层，替代目前的 verification-gate 手动 skill |
| 3 | **PostToolUseFailure 自愈** | PostToolUseFailure | 工具失败时注入修复建议（npm test 失败 → 建议 npm install 先） | 新建 post-tool-failure.sh，提取常见错误模式 → 注入 additionalContext |
| 4 | **SubagentStop 质量门** | SubagentStop | 子代理完成前验证输出质量（不达标则 block 继续） | dispatch-gate 的逆向：出口质检 |
| 5 | **updatedInput 安全沙箱** | PreToolUse | 不阻断命令，而是修改它（加 --dry-run、去掉 -f flag） | guard-redflags.sh 升级：block → modify |
| 6 | **StopFailure 限流韧性** | StopFailure | API 限流时自动保存上下文 + 发送 Telegram 告警 | 新建 stop-failure.sh，复用 session-stop 的 git 安全网逻辑 |

### P1（有价值，可规划）

| # | 模式名 | 来源事件 | 价值 |
|---|--------|---------|------|
| 7 | **ConfigChange 审计日志** | ConfigChange | 检测 settings.json 变更，防止 hook 自身被篡改 |
| 8 | **FileChanged 热重载** | FileChanged | 监听 SOUL/ 文件变更，自动重编译 boot.md |
| 9 | **SubagentStart 资源预算** | SubagentStart | 限制并发子代理数量 + 记录成本预算 |
| 10 | **PermissionRequest 智能审批** | PermissionRequest | 根据上下文自动审批安全操作（Read / Grep = auto-allow） |
| 11 | **SessionEnd 独立事件** | SessionEnd | 从 Stop 中分离出来，Stop 管"继续/停止"，SessionEnd 管"清理/持久化" |
| 12 | **InstructionsLoaded 追踪** | InstructionsLoaded | 记录哪些指令文件被加载，检测指令膨胀 |

### P2（探索性）

| # | 模式名 | 来源事件 | 价值 |
|---|--------|---------|------|
| 13 | **多代理任务协调** | TaskCreated/Completed/TeammateIdle | 在团队模式下协调任务分配和空闲检测 |
| 14 | **HTTP Hook 远程网关** | 所有事件 | 将 hook 决策代理到远程服务（集中管控多个 agent） |
| 15 | **Agent Hook 深度验证** | PreToolUse | 对 Write/Edit 操作启动子代理验证测试覆盖 |

---

## 九、架构启示

### 9.1 "阻断点密度"理论

Claude Code 的 21 个事件中，11 个可阻断。阻断点覆盖了完整的代理执行链：

```
用户输入 → [UserPromptSubmit] → 
  工具请求 → [PreToolUse] → [PermissionRequest] →
    工具执行 →
  工具完成 → [PostToolUse] → [PostToolUseFailure] →
  完成判断 → [Stop] → [StopFailure] →
子代理 → [SubagentStart] → [SubagentStop] →
团队 → [TaskCreated] → [TaskCompleted] → [TeammateIdle] →
配置 → [ConfigChange]
```

这不是"事件系统"，这是一个**完整的控制平面**。每个可能出错的关键路径都有一个拦截点。

### 9.2 "双通道决策"模式

Claude Code 对 PreToolUse 使用了不同于其他事件的决策模式（`hookSpecificOutput.permissionDecision` vs 顶级 `decision`）。原因：PreToolUse 需要三态（allow/deny/ask），其他事件只需要二态（block/allow）。

Orchestrator 目前用统一的 `{"decision":"block/allow"}` 格式，足够但缺少 `ask` 选项（交给用户决定）。

### 9.3 "修改而非阻断"哲学

`updatedInput` 是一个深刻的设计选择。传统 guard 是 block + 报错 + 让 LLM 重试。`updatedInput` 是**透明修改**：命令通过，但参数被安全化了。

这比 block+retry 更高效（省一轮 LLM 调用），更安全（不依赖 LLM 理解错误消息并修正）。

### 9.4 "声明性安全 > 指令性安全"

Hooks 的核心价值：**确定性处理注入到 LLM 生命周期**。

- CLAUDE.md 里写"不要删除系统文件" → LLM 可能忽略（指令性）
- PreToolUse hook 检测 `rm -rf /` 并 block → 100% 拦截（声明性）

Orchestrator 已经理解了这个原则（guard-redflags.sh），但 Claude Code 把它推到了极致：21 个拦截点 × 4 种 handler 类型 = 每个操作都可以被确定性地治理。

---

## 十、总结

Claude Code 的 Hook 系统在 2026 年 Q1 完成了从"安全拦截器"到"完整控制平面"的进化。21 个事件覆盖了代理执行的每个关键路径；4 种 handler 类型（command/http/prompt/agent）提供了从确定性检查到语义判断的全频谱能力；`updatedInput` 引入了"修改而非阻断"的新范式。

Orchestrator 当前覆盖了 6/21 个事件，全部使用 command handler。最大的结构性差距是：

1. **缺少 prompt/agent hooks**：用 LLM 做语义安全判断
2. **缺少 PostToolUseFailure**：失败自愈
3. **缺少 SubagentStop 质量门**：子代理出口质检
4. **缺少 updatedInput**：修改而非阻断
5. **缺少 StopFailure**：API 错误韧性

6 个 P0 模式可以立即实施，预计显著提升 Orchestrator 的治理能力和韧性。

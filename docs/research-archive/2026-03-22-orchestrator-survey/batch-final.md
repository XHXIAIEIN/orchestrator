# 最后一批项目汇总

## mozaik (jigjoy-ai) — B 级
- **URL**: https://github.com/jigjoy-ai/mozaik
- **语言**: TypeScript | **Stars**: 7
- 多模型多 provider 的 agent 编排库
- **可偷**: Zod Schema 约束 AI 规划（LLM 输出合法执行计划）/ WorkUnit Composite 递归树 / Autonomy Slider（人机混合编排）/ 显式状态机替代隐式链 / Hook ClusterHook 组合
- **不偷**: 代码质量一般（拼写错误）、无错误恢复、sequential 模式无上下文传递

## breeze (kevinw-openai) — B 级
- **URL**: https://github.com/kevinw-openai/breeze
- **语言**: TypeScript | **来源**: OpenAI 员工
- Codex agent cron 自动化运行器，极简 ~1500 LOC
- **可偷**: Codex app-server WebSocket JSON-RPC 协议（首次公开使用）/ Agent 作为长驻线程多次 turn / 原子状态写入（tmp+rename）/ 状态跨重启合并 / trigger 与 agent 解耦
- **不偷**: 无多 agent 协作、无 DAG、无 retry

## claude-code-project-template (umiao) — A 级
- **URL**: https://github.com/umiao/claude-code-project-template
- Claude Code 项目脚手架，hook 玩到极致
- **可偷**:
  - **Stop hook LLM-as-judge**（Claude 审查自己是否完成退出协议）⭐⭐⭐⭐⭐
  - **Plan Mode 读写隔离**（TTL 状态开关 + PreToolUse 拦截写操作 + drift counter）⭐⭐⭐⭐⭐
  - **NEEDS-INPUT 协议**（正式的"需要人工输入"标记 + 自动跳过 + 聚合展示）⭐⭐⭐⭐
  - **DB-first + Markdown 投影**（SQLite 管任务，TASKS.md 只读，hook 拦截直接编辑）⭐⭐⭐⭐
  - **hook_utils.py 防御模式**（hook 永远不 crash，异常 exit 0）⭐⭐⭐⭐
  - **自治循环失败区分**（context exhaustion ≠ real failure，有新 commit 就不算失败）⭐⭐⭐⭐
- 核心洞察: "instructions are suggestions, hooks are enforcement"

## Claude Multi-Agent Research (zubayer0077) — B 级
- **URL**: https://github.com/zubayer0077/Claude-Multi-Agent-Research-System-Skill
- 纯 Claude Code 原生多智能体编排
- **可偷**:
  - **工具权限剥夺做约束**（allowed-tools 不含 Write，orchestrator 物理上无法写文件）⭐⭐⭐⭐⭐
  - **Hook 前置意图路由**（user-prompt-submit 在用户输入到达前注入引导）⭐⭐⭐⭐
  - **过程合规检查**（验证"谁干的"而不只是验证结果）⭐⭐⭐⭐
- 局限: 纯 prompt engineering，无运行时保障

## bored (TannerBurns) — A 级
- **URL**: https://github.com/TannerBurns/bored
- **语言**: Rust + React (Tauri 2.x)
- "用管人的方式管 Agent"——看板工作流对接 AI Agent
- **可偷**:
  - **Stage Pipeline + Command Catalog**（workflow 拆成可配置 stage，每 stage 是一个 .md prompt）⭐⭐⭐⭐⭐
  - **Deslop 命令**（专门的"去 AI 代码臭味"流水线工位）⭐⭐⭐⭐⭐
  - **AutoPilot 自选命令**（Agent 看完实现后自己决定要不要跑 review/test）⭐⭐⭐⭐
  - **Sub-run 追踪**（每个 stage 独立记录状态/耗时/成本）⭐⭐⭐⭐
  - **Auto-Clarification 回路**（歧义 → AI 自动消解 → 不行 block 等人 → 恢复）⭐⭐⭐⭐
  - **Session 传递 + Retry 重置**（stage 间传 session 保记忆，retry 时重置避免坏状态传播）⭐⭐⭐⭐
  - **Provider Trait 抽象**（build_command/extract_text/extract_cost/is_available）⭐⭐⭐

## agentic-ai-systems (iulieobraznic) — C 级
- **URL**: https://github.com/iulieobraznic/agentic-ai-systems
- Obsidian 知识库，不是可执行框架
- **可偷**: Prompt Hook 双模式（shell + LLM-as-judge）/ 声明式 agent frontmatter / Evaluator-Optimizer 循环 / Checkpoint+Resume
- **注意**: README 里的 .zip 下载链接可疑，别碰

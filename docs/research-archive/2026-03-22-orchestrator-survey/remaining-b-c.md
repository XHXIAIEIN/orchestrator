# B/C 级项目汇总

## B 级

### Tmux-Orchestrator (Jedward23)
- **URL**: https://github.com/Jedward23/Tmux-Orchestrator
- **Stars**: 1644 | **核心**: tmux 作为 agent runtime
- **可偷**: Self-scheduling (nohup sleep + send-keys 自动醒) / LEARNINGS.md 集体记忆 / Hub-and-Spoke 通信 / PM-oversight slash command
- **不偷**: 文件当 IPC、无结构化协议、硬编码路径

### Ludwig-AI (AlexanderHeffernan)
- **URL**: https://github.com/AlexanderHeffernan/Ludwig-AI
- **语言**: Go | **核心**: CLI 驱动任务编排器
- **可偷**: Git Worktree 沙箱 / Model Fallback Chain (auto→pro→flash→lite + 指数退避 + 部分输出带入重试) / NEEDS_REVIEW 审核协议 / 流式响应持久化 (io.Writer)
- **不偷**: JSON 文件存储、空文件锁、硬编码 Go 工作流

### project-artemis (ajansen7)
- **URL**: https://github.com/ajansen7/project-artemis
- **核心**: 纯 Claude Code 原生求职 agent 系统（抛弃 LangGraph）
- **可偷**: Prompt-as-SOP / 两级记忆 (hot ~70行 + extended 按需) / Learn-from-edit 反馈闭环 (diff→提取教训→追加 lessons) / 跨 Skill 连锁规则 / Sentinel 文件检测
- **不偷**: tmux 并行层太简陋

### voice-ai / Rapida (rapidaai)
- **URL**: https://github.com/rapidaai/voice-ai
- **语言**: Go | **核心**: 语音 AI 编排平台
- **可偷**: 四级优先级 Dispatcher (critical/input/output/low 独立 goroutine) / contextID 旋转中断 / Fan-out Collector / errgroup 并发初始化 / Phase-based Disconnect
- **不偷**: genericRequestor God object、巨大 type-switch

## C 级

### cursor-cli-heavy (karayaman)
- ~450 行，极简 fan-out/fan-in。Tag-based parsing [BEGIN_X]...[END_X]、AI 决定并行度、Synthesis 显式阶段。技术上无突破。

### aintandem-pm (misterlex223)
- Meta-repo + submodules。Workflow→Phase→Step、sync+async 双模式、WebSocket 按 project 分连接。核心引擎私有 404。

### giterm (beegy-labs)
- Tauri SSH 终端，agent 编排在路线图上。Session Manager + Command Channel 模式、FSD 前端分层、xterm 孤儿迁移。

## D 级

### Integration-Registry (gijs-hulsebos)
- 270+ 空 .gitkeep Markdown。零代码零逻辑。唯一亮点：Capabilities/Integration/Prompts 三维度分类思路。

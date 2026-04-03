# Claude Code + Ollama 本地模型配置

## 当前状态（2026-04-02）

**Ollama 本地模型直接连接**（无需 CCR 中间层，CCR 已卸载）

配置方式：环境变量设置在 `~/.bashrc`
```bash
export ANTHROPIC_AUTH_TOKEN="ollama"
export ANTHROPIC_BASE_URL="http://localhost:11434"
```

## 运行方式

重启 shell 后，环境变量自动生效：

```bash
# 用指定模型启动 Claude Code
claude --model qwen3.5:9b
```

或一行命令（不依赖环境变量）：
```bash
ANTHROPIC_AUTH_TOKEN=ollama ANTHROPIC_BASE_URL=http://localhost:11434 claude --model qwen3.5:9b
```

## 可用模型列表

查看本地所有模型：
```bash
curl http://localhost:11434/api/tags | python3 -m json.tool
```

常用模型：
- `qwen3.5:9b` — 轻量级，适合日常对话
- `qwen3.5:4b` — 超轻量
- `qwen3:32b` — 高性能，适合复杂任务
- `deepseek-r1:32b` — 推理能力强
- `gemma3:27b` — 多语言支持
- `mistral-small3.1:24b` — 速度和质量均衡
- `gpt-oss:20b` — 开源 GPT 替代品

## 切回 Anthropic API（云端 Claude）

如果想改回直接用 Claude API（Max 订阅）：

### 方法 1：清理环境变量
```bash
# 编辑 ~/.bashrc，删除或注释掉这两行：
# export ANTHROPIC_AUTH_TOKEN="ollama"
# export ANTHROPIC_BASE_URL="http://localhost:11434"

# 重启 shell，直接运行
claude
```

### 方法 2：临时覆盖环境变量
```bash
unset ANTHROPIC_BASE_URL
unset ANTHROPIC_AUTH_TOKEN
claude
```

## 故障排查

### 模型不存在错误

**症状**：`There's an issue with the selected model (qwen3.5:9b). It may not exist or you may not have access to it.`

**检查清单**：
1. Ollama 是否运行？
   ```bash
   curl http://localhost:11434
   # 应该返回：Ollama is running
   ```

2. 模型是否存在？
   ```bash
   curl http://localhost:11434/api/tags
   # 检查 JSON 中是否有 qwen3.5:9b
   ```

3. 环境变量是否生效？
   ```bash
   echo $ANTHROPIC_BASE_URL
   echo $ANTHROPIC_AUTH_TOKEN
   # 应该分别输出：http://localhost:11434 和 ollama
   ```

**解决方案**：
- 重启 shell（打开新 terminal）加载 `.bashrc`
- 或改用一行命令方式，不依赖环境变量

## 历史：为什么卸载了 CCR

- **CCR（Claude Code Router）**：之前用来路由到本地 Ollama 的中间层
- **问题**：Claude Code 本身就原生支持 Ollama 的 Anthropic 兼容 API（端口 11434）
- **结论**：不需要额外的 router，直接连接更简洁高效
- **卸载日期**：2026-04-02

## 配置文件位置

- Ollama 环境变量：`~/.bashrc`（第 5-7 行）
- Claude Code 设置：`~/.claude/settings.json`
- Ollama 模型目录：通常在系统 Ollama 安装目录

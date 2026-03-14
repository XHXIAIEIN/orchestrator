# 六部建制设计 — 2026-03-15

## 目标

把 Governor 的尚书省从"一个通才 `claude --print`"拆成可路由的专业部门。
不是一次建六个——先建路由机制 + 工部（代码工程），其他部门按需追加。

## 最小方案

### 1. Task spec 新增 department 字段

```python
spec = {
    "problem": "...",
    "department": "engineering",  # 新增：目标部门
    "cwd": "/path/to/project",   # 新增：工作目录（可选）
    ...
}
```

InsightEngine 生成 recommendation 时标注目标部门。
Health check 生成的自修复任务自动标注 `department: "operations"`。

### 2. Governor 路由逻辑

```python
DEPARTMENTS = {
    "engineering": {
        "prompt_prefix": "你是工部——负责代码工程...",
        "default_cwd": None,  # 由 spec.cwd 指定
    },
    "operations": {
        "prompt_prefix": "你是户部——负责系统运维...",
        "default_cwd": "/orchestrator",
    },
    "quality": {
        "prompt_prefix": "你是刑部——负责质量验收...",
        "default_cwd": None,
    },
}

def execute_task(self, task_id):
    spec = task["spec"]
    dept = spec.get("department", "engineering")
    dept_config = DEPARTMENTS.get(dept, DEPARTMENTS["engineering"])

    prompt = dept_config["prompt_prefix"] + "\n\n" + TASK_PROMPT_TEMPLATE.format(...)
    cwd = spec.get("cwd") or dept_config["default_cwd"] or default_cwd

    subprocess.run(["claude", "--print", prompt], cwd=cwd, ...)
```

### 3. 工部（engineering）— 第一个专业部门

负责跨项目代码工程。和通用 executor 的区别：
- 有自己的 prompt prefix（了解项目结构、代码规范）
- 支持 cwd 参数化（可以去 Construct3-RAG 目录干活）
- 执行后自动检查 git status

### 4. 户部（operations）— 自维护

负责 Orchestrator 自身的运维：
- 修复 health check 发现的问题
- 优化采集器
- 管理 DB 大小
- cwd 固定在 /orchestrator

## 不做的

- 暂不建吏部（Agent 发现层）— 阶段 4 的事
- 暂不建兵部（安全）— guard.sh 够用
- 暂不建礼部（通知）— 阶段 5 的事
- 暂不用 Agent SDK — 先用 `claude --print` + 路由验证概念

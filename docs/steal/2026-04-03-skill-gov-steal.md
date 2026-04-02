# Round 36: aresbit/skill-gov — Claude Skills 物理治理 CLI

> 来源: https://github.com/aresbit/skill-gov (34 stars)
> 日期: 2026-04-03
> 分类: Claude Code Tooling / Skill Governance / CLI Utility
> 语言: C17 (纯 C, 零依赖)

---

## 一句话

用 **文件系统 rename 原子操作 + glob 模式匹配** 实现 Claude skills 的批量启用/禁用，失败时自动回滚——思路是把 `.claude/skills/` 下的目录移到 `.disabled/` 子目录来"禁用"skill。

---

## 它解决什么问题

Claude Code 的 skills 系统没有内置的批量启用/禁用机制。当你装了几十个 skill，想要：
- 临时关掉一批不相关的 skill（减少 token 消耗、避免误匹配）
- 切换"skill 配置文件"（工作场景 A 开一组、场景 B 开另一组）
- 排查某个 skill 引发的问题

手动 `mv` 每个目录太蠢，`skill-gov` 就是这个的 CLI 封装。

---

## 架构总览

```
~/.claude/skills/
├── flutter-basics/      ← enabled (正常位置)
├── react-patterns/      ← enabled
├── .disabled/           ← skill-gov 创建的"禁用区"
│   ├── actix-web/       ← disabled (被移到这里)
│   └── rust-macros/     ← disabled
```

**核心机制极其简单**: skill 目录在 `skills/` = 启用，在 `skills/.disabled/` = 禁用。启用/禁用就是 `rename()` 系统调用。

```
┌─────────────┐     ┌──────────────┐     ┌───────────────────┐
│  CLI Parser  │ ──→ │  Skill Scanner│ ──→ │  Batch Move Engine │
│  (Cli struct)│     │  (SkillVec)   │     │  (MoveVec + atomic)│
└─────────────┘     └──────────────┘     └───────────────────┘
      │                    │                       │
      │ parse_cli()        │ scan_dir_skills()     │ atomic_batch_move()
      │ glob/flags/cmd     │ readdir + classify    │ rename + rollback
```

---

## 源码分析

### 文件结构 (3 个文件，约 400 行)

| 文件 | 行数 | 职责 |
|------|------|------|
| `src/main.c` | ~340 | CLI 解析、skill 扫描、批量操作、原子回滚 |
| `src/spclib.c` | ~110 | 工具库: path_join, strdup, glob DP 匹配, 动态数组 |
| `include/spclib.h` | ~15 | 接口声明 |

### 关键数据结构

```c
// 单个 skill 的状态
typedef struct {
    char *name;
    int enabled;   // 1=在 skills/, 0=在 .disabled/
} Skill;

// 一次批量移动的记录（用于回滚）
typedef struct {
    char *src;     // 源路径
    char *dst;     // 目标路径
    char *name;    // skill 名称
} Move;

// CLI 解析结果
typedef struct {
    int list;           // --list 模式
    int dry_run;        // --dry-run 预览
    int force;          // --force 覆盖
    int has_cmd;        // 是否有子命令
    int enable;         // enable vs disable
    int enable_all;     // enableall
    int disable_all;    // disableall
    char **patterns;    // glob 模式列表
    int pattern_count;
} Cli;
```

### 核心流程

1. **parse_cli()** — 手写的参数解析器，支持 `--list`, `enable/disable <patterns>`, `enableall/disableall`, `--dry-run`, `--force`
2. **scan_dir_skills()** — 扫描 `skills/` 和 `skills/.disabled/` 两个目录，用 `readdir` + `stat` 判断子目录，标记 enabled/disabled
3. **run_list()** — 排序后打印 `[x]` / `[ ]` + 颜色
4. **run_batch()** — 对每个 skill 做 glob 匹配，计算需要移动的列表
5. **atomic_batch_move()** — **核心**: 先预检所有源/目标路径，然后逐个 `rename()`，如果中途失败则反向回滚已完成的 move

### Glob 匹配引擎 (`spc_glob_match_ci`)

用 **动态规划** 实现，不是递归回溯：

```c
// dp[i][j] = pattern[0..i] 是否匹配 text[0..j]
// * 匹配任意序列: dp[i][j] = dp[i-1][j] || dp[i][j-1]
// ? 匹配单个字符: dp[i][j] = dp[i-1][j-1]
// 大小写不敏感
```

分配 `(plen+1)*(tlen+1)` 字节的 DP 表，O(P*T) 时间复杂度。对于 skill 名这种短字符串完全够用。

### 原子回滚机制

```c
static int atomic_batch_move(const MoveVec *moves, int *rolled_back, int force) {
    // Phase 1: 预检——检查所有源文件存在、目标不冲突
    for (i = 0; i < moves->len; i++) {
        if (!exists_path(moves->items[i].src)) abort;
        if (!force && exists_path(moves->items[i].dst)) abort;
    }

    // Phase 2: 执行——逐个 rename
    for (i = 0; i < moves->len; i++) {
        if (rename(src, dst) != 0) {
            // Phase 3: 回滚——把已完成的反向 rename 回去
            for (j = i; j > 0; j--) {
                rename(moves[j-1].dst, moves[j-1].src);
                rolled_back++;
            }
            return 1;
        }
    }
    return 0;
}
```

这不是真正的原子操作（没有用 journaling 或 2PC），但对文件系统 rename 来说是最佳实践——预检 + 执行 + 失败回滚。

---

## 值得偷的模式

### P0: 文件系统即状态机

**模式**: 不用数据库、不用 JSON 配置文件、不用 settings.json——目录位置本身就是状态。`skills/foo` = 启用, `skills/.disabled/foo` = 禁用。

**为什么好**:
- 零序列化开销
- 不会出现配置与实际不一致的问题（状态即现实）
- 任何工具都能操作（手动 mv 也行）
- Claude Code 只认 `skills/` 下的目录，所以移走就是禁用

**Orchestrator 可偷**: 我们的 skill 管理也可以用这个模式——与其在 settings.json 里维护一个 enabled/disabled 列表，不如用目录位置。但考虑到 Claude Code 官方可能改 skill 发现机制，这个方案有耦合风险。

### P1: 预检-执行-回滚三阶段

**模式**: 批量操作不要边检查边做，而是：
1. **预检阶段**: 验证所有前置条件（源存在、目标不冲突）
2. **执行阶段**: 顺序执行
3. **回滚阶段**: 失败时反向撤销

**Orchestrator 可偷**: 我们的 agent dispatch、hook 系统可以借鉴这个三阶段模式。目前的 gate function 是单条操作的检查，但没有批量操作的回滚机制。

### P2: 纯 C 写 CLI 工具的工程质量

**模式**: 400 行 C 代码，做了这些事：
- `-std=c17 -Wall -Wextra -Wpedantic -Wconversion -Wshadow` 全警告
- AddressSanitizer + UndefinedBehavior Sanitizer 构建目标
- 手写动态数组（带倍增策略）
- 手写 DP glob 匹配
- 所有 malloc 有 OOM 检查
- `.toolchain` stamp 文件检测编译器变化触发重编译

这是"该用 C 就用 C"的好例子——不是因为酷，而是因为这个工具的需求（纯文件系统操作 + 模式匹配）完全在 C 的甜区。

### P3: Dry-Run 作为一等公民

**模式**: `--dry-run` 不是事后加的补丁，而是从数据结构就支持——先构建完整的 MoveVec，dry-run 时打印它，非 dry-run 时执行它。同一份 move 列表，两种执行路径。

**Orchestrator 可偷**: 我们的 dispatch 系统可以加 dry-run 模式，在真正派单前预览会发生什么。

---

## 局限性 / 不足

1. **只能在同一文件系统内 rename** — 如果 `.disabled/` 在不同挂载点会失败（实际不太可能）
2. **没有 profile/preset 概念** — 不能保存"工作模式 A = 这组 skill"然后一键切换
3. **没有 hook 集成** — 不能在 enable/disable 时触发回调
4. **不感知 SKILL.md 内容** — 纯目录级操作，不知道 skill 的 name/description
5. **Windows 不支持** — POSIX only (`dirent.h`, `unistd.h`, `sys/stat.h`)
6. **commit 历史粗糙** — 5 个 commit，4 个叫 "fix"，说明是快速原型

---

## 与 Orchestrator 的关系

我们的 `.claude/skills/` 管理目前是手动的。值得考虑的方向：

1. **短期**: 借鉴"目录位置即状态"模式，在 orchestrator 的 skill 管理中用 `.disabled/` 目录
2. **中期**: 写一个 skill profile 系统——保存多组 skill 配置，按场景切换
3. **长期**: 集成到三省六部的吏部绩效系统——根据 skill 使用频率和效果，自动推荐启用/禁用

---

## 作者生态速览

aresbit 是一个 skill 收集/创建狂人，436 个 repo，大量 fork + 自建 skill：
- `fetch-skill` (93★) — 最受欢迎的项目
- `skill-creator` — 自动把文档/repo/PDF 转成 Claude skill
- `skillsfather` — 自主 skill 提取和持续学习
- `agent-proc-gov` — 用 tty 重定向做 agent 进程治理（ptrace 注入）
- `cagent` — Rust 写的 C agent

同一个人写了 skill-gov（技能治理）和 agent-proc-gov（进程治理），说明他在思考 agent 的"治理层"——不是让 agent 更强，而是让 agent 更可控。

---

## 总结

skill-gov 技术上不复杂，但思路值得偷：**文件系统位置即状态** + **批量操作的预检-回滚** + **dry-run 一等公民**。最大的洞察是：Claude skills 的启用/禁用可以完全绕过配置文件，用目录结构本身表达状态。这种"最蠢的方案往往最稳"的哲学，在我们的 orchestrator 里也适用。

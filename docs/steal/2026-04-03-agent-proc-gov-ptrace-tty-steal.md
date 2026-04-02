# Steal: aresbit/agent-proc-gov — ptrace + TTY Redirection for Agent Process Governance

> Source: https://github.com/aresbit/agent-proc-gov (fork of pasky/retty)
> Date: 2026-04-03
> Depth: Implementation-level (full source read)

## TL;DR

这不是一个典型的 "agent framework"——它是一个 **Linux 进程级别的 TTY 劫持工具**，用 ptrace syscall 注入 + 伪终端重定向，实现对**已运行进程**的实时附着/分离，**不需要目标进程提前做任何准备**。项目名 "agent-proc-gov" 暗示了一个思路：用操作系统级原语（而非应用层 API）来治理 agent 进程。

核心价值不在代码本身（C + 内联汇编，2006 年的产物），而在**思维模式**：当你的 agent 是一个黑盒进程时，如何从外部夺取它的 I/O 控制权。

---

## 1. 解决什么问题

| 场景 | 传统方案 | agent-proc-gov 方案 |
|------|----------|---------------------|
| Agent 进程失去 terminal | 重启 | ptrace 附着，重定向 fd 到新 PTY |
| 需要观察 agent 的 stdin/stdout | 提前用 screen/tmux | 事后附着，零准备 |
| Agent 跑在 detached session 里 | 只能看日志 | 实时接管 I/O 流 |
| 需要向运行中的 agent 注入输入 | kill -SIGUSR / named pipe | 直接写入其 stdin fd |

**一句话**：screen/tmux 需要你**提前**把进程放进去；retty/agent-proc-gov 让你**事后**附着到任何进程。

---

## 2. 核心机制：ptrace + TTY Redirection

### 2.1 总体流程

```
retty PID
  │
  ├─ 1. 创建新的 pseudo-terminal (PTY master/slave)
  │     posix_openpt() → grantpt() → unlockpt() → ptsname()
  │
  ├─ 2. ptrace(PTRACE_ATTACH, pid) — 暂停目标进程
  │
  ├─ 3. 注入 shellcode/syscall 到目标进程栈上
  │     ├─ dup(0/1/2) → 保存原始 fd
  │     ├─ close(0), close(1), close(2)
  │     ├─ open(pts_path, O_RDWR) → 获得 PTY slave fd
  │     ├─ dup2(pts_fd, 0), dup2(pts_fd, 1), dup2(pts_fd, 2)
  │     ├─ ioctl(TCGETS/TCSETS) → 同步终端属性
  │     └─ kill(getpid(), SIGWINCH) → 通知窗口大小变化
  │
  ├─ 4. ptrace(PTRACE_DETACH) — 恢复目标进程运行
  │
  └─ 5. select() 主循环：PTY master ↔ 本地 stdin/stdout
        ├─ PTY master 有数据 → write(1) 显示到当前终端
        ├─ stdin 有数据 → process_escapes() → write(ptm) 发给目标
        └─ 检测 escape sequence (Enter + ` + d) → 触发 detach
```

### 2.2 两代实现对比

#### 原版 (pasky/retty) — 汇编 shellcode 注入

原版用 **ia32 汇编生成 bytecode**，通过 `bytecode.pl` 转成 C 数组 `bc-attach.i`，然后：

```c
// 原版 inject_attach() 核心
static unsigned char attach_code[] = {
    #include "bc-attach.i"  // 编译好的 shellcode
};

// 1. PTRACE_ATTACH 暂停目标
ptrace(PTRACE_ATTACH, pid, 0, 0);

// 2. 把 shellcode 写到目标进程的栈上
regs.esp -= sizeof(attach_code);
write_mem(pid, attach_code, sizeof(attach_code)/sizeof(long), regs.esp);

// 3. 把 PTY slave 路径也写到栈上
regs.esp -= n*4;
write_mem(pid, ptsname, n, regs.esp);

// 4. 修改 EIP 指向 shellcode
regs.eip = codeaddr + 8;  // 跳过 16 字节 NOP sled
ptrace(PTRACE_SETREGS, pid, 0, &regs);

// 5. 让 shellcode 跑完（用 SIGWINCH 做同步信号）
ptrace(PTRACE_CONT, pid, 0, SIGWINCH);
// 等待 shellcode 内部的 kill(getpid(), SIGWINCH)

// 6. 从栈上读回保存的旧 fd
oldin = ptrace(PTRACE_PEEKDATA, pid, regs.esp + 0x8, NULL);
oldout = ptrace(PTRACE_PEEKDATA, pid, regs.esp + 0x4, NULL);
olderr = ptrace(PTRACE_PEEKDATA, pid, regs.esp + 0x0, NULL);
```

汇编 shellcode (`attach-ia32-linux.S`) 的关键操作序列：
```asm
; 1. open(pts_path, O_RDWR) → 获得新终端的 fd
; 2. dup(0), dup(1), dup(2) → 备份原始 fd（压栈保存）
; 3. close(0), close(1), close(2) → 关闭原始 fd
; 4. dup2(pts_fd, 0/1/2) → 重定向到新 PTY
; 5. ioctl(TCGETS) + ioctl(TCSETS) → 复制终端属性
; 6. close(pts_fd) → 清理
; 7. kill(getpid(), SIGWINCH) → 通知 retty 主进程完成
; 8. 恢复寄存器，ret → 目标进程继续正常执行
```

**精妙之处**：shellcode 用 `add $0x12000000, %esp` 修正栈指针（实际值在注入时动态 patch），让目标进程的栈恢复到注入前的状态。

#### Fork 版 (aresbit/agent-proc-gov) — 纯 C ptrace 远程 syscall

Fork 版抛弃了汇编 shellcode，改用 **ptrace 远程 syscall 执行**：

```c
// execute_syscall() — 在目标进程上下文中执行 syscall
static long execute_syscall(pid_t pid, long syscall_no, long arg1, long arg2, long arg3) {
    struct user_regs_struct regs, orig_regs;

    ptrace_getregs(pid, &regs);
    orig_regs = regs;

    // 设置 syscall 参数（x86_64 ABI）
    regs.orig_rax = syscall_no;
    regs.rdi = arg1;
    regs.rsi = arg2;
    regs.rdx = arg3;
    ptrace_setregs(pid, &regs);

    // PTRACE_SYSCALL 让目标执行到 syscall 入口
    ptrace_syscall(pid);  // syscall entry
    ptrace_syscall(pid);  // syscall exit

    // 读取返回值
    ptrace_getregs(pid, &regs);
    long result = regs.rax;

    // 恢复原始寄存器（除了 rax）
    // ...
    return result;
}

// attach 流程
int attach_process_to_terminal(pid_t pid, const char* ptsname, ...) {
    ptrace_attach(pid);

    // 把 PTS 路径写到目标栈上
    unsigned long pts_path_addr = write_string_to_process(pid, ptsname);

    // 在目标进程中执行 open(pts_path, O_RDWR)
    long pts_fd = execute_syscall(pid, SYS_open, pts_path_addr, O_RDWR, 0);

    // 在目标进程中执行 dup2(pts_fd, 0/1/2)
    execute_syscall(pid, SYS_dup2, pts_fd, 0, 0);
    execute_syscall(pid, SYS_dup2, pts_fd, 1, 0);
    execute_syscall(pid, SYS_dup2, pts_fd, 2, 0);

    ptrace_detach(pid);
}
```

**关键改进**：
- x86_64 支持（原版只支持 ia32）
- 不需要可执行栈（原版需要 `-z execstack`）
- 更安全：不注入任意代码，只触发已有的 syscall
- 使用 `sp.h` 单头文件库替代 printf（结构化日志）

### 2.3 数据结构

```c
// 全局状态（retty.c）
static int oldin, oldout, olderr;  // 备份的原始 fd
static int die, intr;              // 退出/中断标志
static int stin=0, sout=1, serr=2; // 可配置的目标 fd 编号
static pid_t pid;                   // 目标进程 PID
static struct termios t_orig;       // 原始终端设置
static int ptm;                     // PTY master fd

// ProcessState（attach.c 新增）
typedef struct {
    int old_stdin, old_stdout, old_stderr;
    int pts_fd;
    struct termios saved_termios[3];
} ProcessState;

// Escape sequence 状态机
enum { ST_NONE, ST_ENTER, ST_ESCAPE } state;
```

---

## 3. 可偷模式

### P0: 进程级 I/O 劫持（Agent 治理原语）

**模式**：不通过应用层 API，而是通过 OS 原语（ptrace + fd redirect）控制 agent 进程的 I/O。

**Orchestrator 适用场景**：
- Claude Code sub-agent 进程挂死或失去响应 → 附着其 stdin，注入中断信号
- 长时间运行的 agent 需要实时观察输出 → 不杀进程，直接接管 stdout
- Agent 的 TTY 丢失（SSH 断开等） → 重新绑定到新终端

**关键洞察**：这比 kill + restart 高级得多。进程的**内存状态、打开的文件、网络连接**全部保留，只是 I/O 通道被重新路由。对于有状态的 agent（如正在执行多步任务），这意味着可以**不丢失上下文**地恢复控制。

### P1: PTY 中间人模式（Agent I/O 审计）

**模式**：在 agent 和终端之间插入一个 PTY 中间层，实现透明的 I/O 监控和审计。

```
正常: Agent ←→ Terminal
劫持: Agent ←→ PTY slave ←→ [retty select() loop] ←→ PTY master ←→ Your Terminal
                                    ↓
                              可以在这里：
                              - 记录所有 I/O
                              - 过滤/修改输出
                              - 注入输入
                              - 实现 escape sequence 控制
```

**对 Orchestrator 的价值**：
- Guard hook 可以在 PTY 中间层拦截危险命令
- 审计日志不依赖 agent 配合
- 可以实现"暂停"——停止转发 stdin，agent 的 read() 阻塞

### P2: Blind Launch + Deferred Attach（先跑后管）

**blindtty** 工具的思路：先启动一个 detached 进程，以后再 attach。

```c
// blindtty: forkpty + execvp → 进程在 PTY 中运行但没人连接
pid = forkpty(&ptm, NULL, NULL, NULL);
if (pid == 0) {
    execvp(child_argv[0], child_argv);
}
// 输出 PID，用户以后用 retty PID 附着
```

**Orchestrator 适用场景**：
- 批量启动 agent 任务，不立即需要交互
- 后台 agent 出问题时才 attach 排查
- 资源调度：先 launch，按需 attach/detach

### P3: SIGWINCH 同步协议

**模式**：用 SIGWINCH 作为 shellcode 执行完成的同步信号。

```c
// retty 发 SIGWINCH 给目标
ptrace(PTRACE_CONT, pid, 0, SIGWINCH);
// shellcode 内部最后一步也发 SIGWINCH
// retty 等待这个信号确认完成
do {
    ptrace(PTRACE_CONT, pid, 0, SIGWINCH);
    wait(&waitst);
} while (WSTOPSIG(waitst) != SIGWINCH);
```

巧妙利用了 SIGWINCH 的特性：
1. 终端程序通常已经处理 SIGWINCH（窗口大小变化），不会崩溃
2. 可以中断阻塞的 read() syscall
3. 作为完成信号不会与正常信号冲突

### P4: Escape Sequence 状态机

简洁的三状态机实现 in-band 控制：

```
ST_NONE → 收到 \n/\r → ST_ENTER → 收到 ` → ST_ESCAPE → 命令字符
                                   └─ 其他 → ST_NONE
```

这是一个**通用的带内控制模式**：在数据流中嵌入控制信号，无需额外通道。SSH 的 `~.` 用同样的模式。

---

## 4. 与 "简单杀/重启" 的本质区别

| 维度 | kill + restart | ptrace + fd redirect |
|------|----------------|----------------------|
| 进程状态 | 丢失 | 保留 |
| 内存中的数据 | 丢失 | 保留 |
| 打开的文件/网络连接 | 关闭 | 保留 |
| 执行到一半的任务 | 必须重做 | 继续执行 |
| 需要目标进程配合 | 是（graceful shutdown） | 否 |
| 延迟 | 重启时间 | 毫秒级 |
| 适用场景 | 无状态服务 | 有状态 agent |

---

## 5. 局限性与现实考量

1. **Linux only** — ptrace 是 Linux 特有的（macOS 有类似但不同的 API）
2. **Same UID 或 root** — 安全限制，Yama ptrace_scope 可能阻止
3. **x86/x86_64 only** — 寄存器操作是架构相关的
4. **不处理 /dev/tty** — 有些程序直接打开 /dev/tty 而不用 fd 0/1/2
5. **不切换控制终端** — session leader / controlling terminal 的关系没完全处理
6. **代码质量**：fork 版有很多 placeholder（`generate_attach_code` 返回 NOP sled），实际用的是 `execute_syscall` 路径

---

## 6. Orchestrator 可实施项

| 优先级 | 项目 | 难度 | 收益 |
|--------|------|------|------|
| **考虑** | Agent I/O 审计中间层 | 中 | Guard hook 可以在 PTY 层拦截，不依赖 agent 内部实现 |
| **考虑** | Blind launch + deferred attach 模式 | 低 | 批量 agent 调度时有用 |
| **观望** | 进程级 fd 重定向 | 高 | 仅 Linux，对 Windows 环境不适用 |
| **借鉴** | Escape sequence 带内控制模式 | 低 | 在任何文本流中嵌入控制信号的通用模式 |

---

## 7. 仓库元数据

- **Fork of**: [pasky/retty](https://github.com/pasky/retty)（2006 年，Petr Baudis + Jan Sembera）
- **Fork 改动**（2026-03-29，4 commits by aresbit + claude）:
  - 从 ia32 汇编 shellcode 迁移到 x86_64 ptrace 远程 syscall
  - 引入 `sp.h` 单头文件库（结构化日志、跨平台基础设施）
  - C11 标准化，添加现代 Makefile（clang-tidy, clang-format）
  - 添加 CLAUDE.md（Claude Code 辅助开发的上下文文件）
- **语言**: C (99.2%)
- **License**: GPL-2.0
- **状态**: 实验性——attach.c 的代码注入路径是 placeholder，实际工作的是 ptrace 远程 syscall 路径

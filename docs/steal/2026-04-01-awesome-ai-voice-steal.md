# Round 28: wildminder/awesome-ai-voice — AI 语音模型策展清单偷师

**Source**: https://github.com/wildminder/awesome-ai-voice
**Type**: Curated awesome-list（非代码仓库）
**Date**: 2026-04-01
**Scope**: 40+ 开源 TTS / 音乐生成 / 音频恢复 / ASR 模型

---

## 一、信息架构模式（可偷）

### P1-1: Quick Comparison Table — 决策支持前置

**模式**: 每个分类开头放一个标准化对比表，5-6 个关键维度，让读者 10 秒内筛选。

```
| Model | Voice Cloning | ASR | Languages | Streaming | License |
```

**为什么好**: 不逼人读完 40 个 `<details>` 才能做决策。把"浏览"和"深读"分成两层。

**Orchestrator 应用**: 偷师报告的模式对比表可以学这个——目前我们的 steal 报告都是线性叙述，缺少"一眼扫完全局"的入口。

**状态**: 📋 P1 — 下一份 steal 报告尝试

---

### P1-2: Collapsible Detail Cards — 渐进式披露

**模式**: 每个模型用 `<details>` 折叠，展开后是**完全标准化**的 Feature/Value 表 + Links badge 行。

模板结构：
```
<details id="model-name">
  <summary>Model Name</summary>
  ### Model Name
  **Description:** ...
  **Release Date:** ...
  | Feature | Value | （标准化字段）
  **Key Innovation:** ...（仅在有亮点时出现）
  **Links:** GitHub | HuggingFace | arXiv | Demo
</details>
```

**为什么好**: 40+ 条目如果全展开，README 会有上万行。折叠 = 信息密度管理。

**Orchestrator 应用**: 我们的 steal 总索引 (`orchestrator_steal_consolidated.md`) 目前是纯列表，可以考虑分层：索引表 → 折叠详情。

**状态**: 📋 P1 — 索引重构时采用

---

### P1-3: Multi-Dimensional Taxonomy — 领域切分

**模式**: 不是把所有音频模型丢一起，而是切成 5 个维度：
1. **TTS** — 文本转语音（主力）
2. **Music Generation** — 音乐生成
3. **Anything to Audio** — 多模态到音频
4. **Audio Restoration** — 音频修复/增强
5. **ASR** — 语音识别

每个维度有独立的对比表。

**为什么好**: 避免苹果和橘子放一起比。TTS 的关键维度（Voice Cloning / Streaming / Latency）跟音乐生成的关键维度（Lyrics Support / Duration / Instrument Control）完全不同。

**Orchestrator 应用**: 我们的偷师体系已有按 Round 分类，但缺少按**模式类型**的交叉索引（prompt 模式 / 架构模式 / 工程模式 / 治理模式）。

**状态**: 📋 P2 — 索引增加维度标签

---

## 二、领域地图 — 2026 AI 语音 SOTA 总览

### 趋势观察

| 趋势 | 证据 | 对 Orchestrator 的意义 |
|------|------|----------------------|
| **LLM backbone 统治 TTS** | Qwen3-TTS, GLM-TTS, Orpheus (Llama-3b), Spark-TTS (Qwen2.5) 全是 LLM 架构 | 语音能力可以跟 LLM 共享基础设施 |
| **超轻量 on-device** | KittenTTS 15M/25MB, Kokoro 82M, SoproTTS 135M/$100 训练, NovaSR 52kB | 边缘部署门槛已经低到离谱 |
| **Streaming 成标配** | 35/40 个模型支持 streaming，TTFA 低到 97-300ms | 实时语音交互已是基线能力 |
| **RL 对齐进入 TTS** | GLM-TTS (Multi-Reward RL), Fish S2 Pro (RL alignment), PrismAudio (Fast-GRPO) | TTS 质量调优开始学 LLM 的 RLHF 路线 |
| **Tokenizer-free 路线** | VoxCPM (tokenizer-free), LongCat-AudioDiT (waveform latent space) | 减少 tokenization 的信息损失 |
| **中文方言覆盖** | Fun-CosyVoice 18 方言, SoulX-Podcast 四川话/河南话 | 中文 TTS 已到方言级别 |

---

## 三、Orchestrator 实战价值评估

### TTS 候选（给 Telegram Bot / Claw 用）

| 模型 | 参数量 | 中文 | 延迟 | License | 推荐理由 |
|------|--------|------|------|---------|---------|
| **Kokoro-82M** | 82M | ❌ | 快 | Apache-2.0 | 最轻量商用可用，8 语言 54 音色 |
| **KittenTTS** | 15-80M | ❌ | 极快 | Apache-2.0 | 无 GPU 即可跑，25MB |
| **Spark-TTS** | 0.5B | ✅ | 流式 | Apache-2.0 | Qwen2.5 backbone，中英双语，轻量 |
| **Fun-CosyVoice 3.0** | 0.5B | ✅ | 150ms | Apache-2.0 | 阿里出品，方言支持，production-ready |
| **Fish Speech** | 0.5B (mini) | ✅ | 流式 | Apache-2.0 | 8 语言，成熟项目 |

**推荐路线**:
- **快速原型**: Kokoro-82M（最轻量，英文先行）
- **中文 production**: Fun-CosyVoice 3.0 或 Spark-TTS（0.5B 级别，中英双语）
- **边缘/离线**: KittenTTS（无 GPU 要求）

### 音乐生成候选（QQ 音乐采集器延伸）

| 模型 | 中文歌词 | VRAM | License | 推荐理由 |
|------|---------|------|---------|---------|
| **ACE-Step 1.5** | ✅ (50+ 语言) | <4GB | MIT | 本地音乐生成 SOTA，超低 VRAM |
| **LeVo 2** | ✅ | 12-22GB | Apache-2.0 | 腾讯出品，商用级品质 |

### ASR 候选（语音输入→Orchestrator 指令）

| 模型 | 语言 | 特色 | License |
|------|------|------|---------|
| **FunASR** | 50+ | VAD + 说话人分离 + 情感识别 + 时间戳 | MIT |
| **VibeVoice-ASR** | 50+ | 60 分钟长音频处理 | MIT |

---

## 四、可偷模式总结

| # | 模式 | 优先级 | 应用场景 | 状态 |
|---|------|--------|---------|------|
| P1-1 | Quick Comparison Table（决策前置） | P1 | steal 报告格式 | 📋 待实施 |
| P1-2 | Collapsible Detail Cards（渐进披露） | P1 | steal 总索引重构 | 📋 待实施 |
| P1-3 | Multi-Dimensional Taxonomy（维度切分） | P2 | steal 索引交叉标签 | 📋 待评估 |
| P1-4 | TTS 模型候选池 | P1 | Bot 语音输出能力 | 📋 待评估需求 |
| P1-5 | ASR 模型候选池 | P2 | 语音输入→指令 | 📋 待评估需求 |
| P1-6 | 音乐生成候选池 | P3 | QQ 音乐采集器延伸 | 📋 未来可能 |

---

## 五、结构性观察

这个 repo 本身星数不多但**策展质量极高**：
- 40+ 模型每个都有**标准化 feature table**，不是随便列个链接
- 对比表的维度选择很精准（Voice Cloning / Streaming / License 是 TTS 选型的核心决策轴）
- 按发布日期倒序 = 最新的排最前，对追踪 SOTA 很友好
- Badge 链接统一（GitHub / HuggingFace / arXiv / Demo），不需要跳到每个 repo 去找入口

**对比我们 steal 索引的差距**: 我们的 `orchestrator_steal_consolidated.md` 是按 Round 线性排列 + 纯文本描述，缺少：
1. 顶部对比表（哪些偷了/没偷/优先级一目了然）
2. 按模式类型的交叉索引
3. 标准化的模式卡片格式

这三个是下次索引重构的方向。

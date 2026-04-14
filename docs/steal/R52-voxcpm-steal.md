# R52 — VoxCPM Steal Report

**Source**: https://github.com/openBMB/VoxCPM | **Stars**: 12,447 | **License**: Apache-2.0
**Date**: 2026-04-14 | **Category**: Streaming Audio Pipeline / Real-time Model Composition

## TL;DR

VoxCPM 是清华 OpenBMB 团队的无 tokenizer 语音合成模型。核心架构是 **三阶段串联 + 可中断流式生成**：LM（语义）→ Residual LM（声学）→ LocDiT CFM（扩散解码）。对 orchestration 最有价值的不是 TTS 本身，而是它在实时流水线里处理状态管理、缓存、badcase 重试、LoRA 热切换的工程模式——这些 pattern 直接可搬到 agent 流水线。

五个可偷结构：
1. **双轨生成 + 停止谓词**：两个 LM 并行维护状态，一个 stop head 决定何时终止自回归 — 对 agent 的 "何时停止 tool call loop" 问题
2. **Prompt Cache 分离**：固定上下文预计算一次，后续调用复用 — agent session 的 prefix cache 模式
3. **streaming_prefix_len 平滑**：流式产出时用 N 个前缀 patch 保证解码连续性 — agent streaming response 的 overlap buffer 模式
4. **LoRALinear buffer scaling**：用 `register_buffer` 而非 parameter 存 scaling factor，`fill_()` 原地修改不触发 torch.compile 重编译 — 运行时热切换的通用技巧
5. **next_and_close 惯用语**：强制关闭部分消耗的 generator，防止 inference_mode 清理被 GC 延迟

---

## Architecture Overview

```
VoxCPM (core.py — Pipeline Facade)
├── VoxCPMModel / VoxCPM2Model (选型由 config.json arch 字段决定)
│   ├── base_lm: MiniCPM4 (文本语义 LM, StaticKVCache)
│   ├── residual_lm: MiniCPM4 浅版 (声学残差 LM, StaticKVCache)
│   ├── feat_encoder: VoxCPMLocEnc (音频 patch → LM 空间)
│   ├── feat_decoder: UnifiedCFM (流匹配扩散解码器)
│   │   └── estimator: VoxCPMLocDiT (Transformer backbone)
│   ├── fsq_layer: ScalarQuantizationLayer (音频 token 量化)
│   └── stop_head: 2-class classifier (停止谓词)
├── ZipEnhancer (可选降噪，ModelScope ANS)
└── TextNormalizer (可选文本规范化，lazy init)

生成流程:
  build_prompt_cache() → _generate_with_prompt_cache()
    → _inference() [自回归循环]
      → feat_decoder() [每 step 跑一次 CFM]
      → stop_head() [决定是否 break]
      → base_lm.forward_step() + residual_lm.forward_step() [推进状态]
    → audio_vae.decode() [latent → waveform]
```

**V1 → V2 演化**：patch_size 2→4，residual_lm 层数 6→8，scalar_quantization_latent_dim 256→512，新增 reference_wav（独立音色克隆通道，区别于 prompt_wav 的音频续写）。

---

## Steal Sheet

### P0 — 双 Generator 接口 + next_and_close 惯用语

**问题**：部分消耗的 `torch.inference_mode()` generator 被 GC 延迟析构，引发资源泄漏。

**他们的解法**：
```python
# model/utils.py
def next_and_close(gen):
    try:
        return next(gen)
    finally:
        gen.close()  # 强制触发 generator 的 GeneratorExit，不等 GC

# 调用侧
def generate(self, *args, **kwargs) -> np.ndarray:
    return next_and_close(self._generate(*args, streaming=False, **kwargs))

def generate_streaming(self, *args, **kwargs) -> Generator:
    return self._generate(*args, streaming=True, **kwargs)

# _generate 内部用 try/finally 保证 temp file 清理
def _generate(self, ...) -> Generator:
    temp_files = []
    try:
        ...
        if streaming:
            try:
                for wav, _, _ in generate_result:
                    yield wav
            finally:
                generate_result.close()  # streaming 路径也主动关闭
        else:
            wav, _, _ = next_and_close(generate_result)
            yield wav
    finally:
        for tmp_path in temp_files:  # 无论如何清理临时文件
            os.unlink(tmp_path)
```

**转移到 orchestration**：agent 的 streaming tool call loop 里，子 generator 一旦不再需要（比如 early stop、用户取消），应立即 `.close()` 而非等 GC。当前 `src/channels/wake.py` 的 streaming path 是否有类似模式？

---

### P0 — Prompt Cache 分离：固定前缀预计算，运行时复用

**问题**：每次生成都重新编码 prompt audio 浪费算力。

**他们的解法**：
```python
def build_prompt_cache(self, prompt_text, prompt_wav_path):
    # 只做音频编码（VAE encode），返回纯数据 dict
    audio_feat = self.audio_vae.encode(audio)
    return {
        "prompt_text": prompt_text,
        "audio_feat": audio_feat,  # 不含 KV cache！
    }

def merge_prompt_cache(self, original_cache, new_text, new_audio_feat):
    # 将本次生成结果追加进 cache，用于多轮对话稳定音色
    return {
        "prompt_text": original_cache["prompt_text"] + new_text,
        "audio_feat": torch.cat([original_cache["audio_feat"], new_audio_feat], dim=0),
    }
```

注意 KV cache 没有被序列化进 prompt_cache——它在 `_inference` 里用 `fill_caches()` 从 prefill 结果动态重建，避免了 cache 跨调用状态污染。

**转移到 orchestration**：
- Agent session prefix（system prompt + fixed context）可以预计算并缓存，每次新 turn 只 fill，不重新 prefill
- `merge_prompt_cache` 的滚动合并模式 = 对话历史的增量压缩策略

---

### P0 — streaming_prefix_len：overlap buffer 平滑流式边界

**问题**：流式逐 patch 解码时，单个 patch 的音频解码有 boundary artifact（拼接不连续）。

**他们的解法**：
```python
# 每次 yield 时，不只输出当前 patch，而是取最近 N 个 patch 一起解码
if streaming:
    pred_feat_chunk = torch.cat(pred_feat_seq[-streaming_prefix_len:], dim=1)
    feat_pred = rearrange(pred_feat_chunk, "b t p d -> b d (t p)")
    yield feat_pred, pred_feat_seq

# 解码端只取最后一个 patch 长度的音频（前面是上下文）
decode_audio = self.audio_vae.decode(latent_pred)
decode_audio = decode_audio[..., -patch_len:].squeeze(1).cpu()
```

本质是 **sliding window decode with overlap**：用历史 context 让解码器有更好的初始状态，只输出窗口最后一段。

**转移到 orchestration**：
- Agent streaming response 里，每次 yield 时携带前几个 token 的 context 再 decode，可以改善 LLM streaming 的分词边界问题
- BlockStreamer 的 chunk 拼接逻辑可以借鉴这个 overlap 思路

---

### P1 — LoRALinear：buffer scaling 实现运行时热切换

**问题**：`torch.compile` 遇到 parameter 值变化会触发重编译，导致 LoRA enable/disable 切换极慢。

**他们的解法**：
```python
class LoRALinear(nn.Module):
    def __init__(self, base, r, alpha, dropout):
        ...
        self._base_scaling = alpha / r
        # persistent=False: 不进 state_dict，不影响 checkpoint 兼容性
        self.register_buffer("scaling", torch.tensor(self._base_scaling), persistent=False)

    def set_enabled(self, enabled: bool):
        # fill_() 原地修改，不触发重编译
        self.scaling.fill_(self._base_scaling if enabled else 0.0)

    def forward(self, x):
        result = F.linear(x, self.weight, self.bias)
        lora_out = F.linear(F.linear(x, self.lora_A), self.lora_B)
        return result + self.dropout(lora_out) * self.scaling  # scaling 是 buffer
```

另一个细节：`LoRALinear` 直接持有原 `nn.Linear` 的 `weight` 和 `bias`（不是 copy），state_dict key 结构与原 `nn.Linear` 一致，加载预训练权重无需 key 映射。

**转移到 orchestration**：
- Agent 的 "behavior mode 切换"（比如 cautious vs aggressive reasoning）如果通过 buffer 而非 parameter 控制，可以在 compiled graph 里热切换
- Plugin enable/disable 的状态机可以参考这个 fill_ 模式

---

### P1 — StaticKVCache：预分配 + fill_caches 分离 prefill/decode 阶段

```python
class StaticKVCache:
    def __init__(self, num_layers, num_kv_heads, dim_kv_head, batch_size, device, dtype, max_length=8192):
        # 一次性分配全部显存，避免动态 alloc
        self.kv_cache = torch.zeros(2, num_layers, batch_size, num_kv_heads, max_length, dim_kv_head, ...)
        self.current_length = 0

    def fill_caches(self, kv_caches):
        # prefill 结果写入静态 buffer
        self.current_length = kv_caches[0][0].size(2)
        for i in range(self.num_layers):
            self.kv_cache[0, i, :, :, :self.current_length, :] = kv_caches[i][0]

    def step(self) -> int:
        # decode 阶段每步推进一个位置
        ret = self.current_length
        self.current_length += 1
        return ret
```

prefill 和 decode 用不同路径（`forward(is_causal=True)` vs `forward_step()`），KV cache 在 prefill 后一次性 fill 进静态 buffer，decode 阶段只做单步 step()。

**转移到 orchestration**：
- Agent 的 system prompt + history 是 "prefill"，新 turn 是 "decode"
- 如果用 prefix caching，分离这两个阶段的 buffer 可以避免每次请求重新填充固定部分

---

### P2 — 配置驱动架构选型：config.json arch 字段

```python
# core.py — facade 层做版本路由
config_path = os.path.join(voxcpm_model_path, "config.json")
arch = config.get("architecture", "voxcpm").lower()

if arch == "voxcpm2":
    self.tts_model = VoxCPM2Model.from_local(...)
elif arch == "voxcpm":
    self.tts_model = VoxCPMModel.from_local(...)
else:
    raise ValueError(f"Unsupported architecture: {arch}")
```

V1/V2 对外接口完全相同，版本差异封装在 Model 内部。Facade 只做 dispatch，调用方无感知。

**转移到 orchestration**：agent dispatch 层按 agent version/capability 路由，而非在调用侧 if/else。

---

### P2 — 控制指令内联编码：`(control)text` 前缀协议

```python
# app.py
final_text = f"({control}){text}" if control else text
# → "(年轻女性，温柔甜美)VoxCPM2 is a TTS model..."
```

控制指令不是独立字段，而是直接内联进文本序列的前缀括号格式。模型在训练时见过这个格式，推理时直接解析。

**转移到 orchestration**：agent instruction 注入可以内联而非独立字段——节省 API roundtrip，利用模型的 in-context 解析能力。

---

### P2 — Badcase 重试：比例门控 + 最大次数上限

```python
retry_badcase_times = 0
while retry_badcase_times < retry_badcase_max_times:
    inference_result = self._inference(...)
    latent_pred, pred_audio_feat = next_and_close(inference_result)

    if retry_badcase:
        if pred_audio_feat.shape[0] >= target_text_length * retry_badcase_ratio_threshold:
            # 音频长度与文本长度比例超阈值 → 判定为 badcase
            retry_badcase_times += 1
            continue
        else:
            break  # 质量合格，退出
    else:
        break
```

注意：streaming 模式下 retry 被强制禁用（不合理），并用 `warnings.warn` 告知而非 raise。

**转移到 orchestration**：
- LLM output quality gate：output token 数 / input token 数超阈值 → 判定为可能 hallucination，触发重试
- retry_badcase 禁用 streaming 的 trade-off 对 agent 同样存在：质量保障 vs 延迟

---

## Comparison Matrix

| 维度 | VoxCPM | Orchestrator 现状 | 可偷程度 |
|------|--------|-----------------|---------|
| 流式生成 | 每 patch yield，sliding window overlap | BlockStreamer 按行/段输出 | P1：overlap buffer 思路 |
| Prompt Cache | 音频特征预计算，运行时 fill_caches | 无显式 prefix cache | P0：session prefix cache 分离 |
| Generator 清理 | next_and_close 强制 close | 未知（需核查 wake.py） | P0：立即应用 |
| 重试策略 | 比例门控 + 次数上限 | cron jitter（R49） | P1：质量门控维度 |
| 架构版本路由 | config.json arch 字段 | 无 | P2：agent capability dispatch |
| LoRA 热切换 | buffer scaling，fill_() | 无 | P2：behavior mode switch |
| 状态机双轨 | base_lm + residual_lm 并行 | 无 | P1：多 LM 协作推理参考 |
| 停止谓词 | stop_head 2-class 分类器 | max_steps / timeout | P1：learned stop condition |

---

## Gaps

1. **错误处理不对称**：`cmd_batch` 里 per-item 异常被 `except Exception` 吃掉打印后继续，没有 partial failure 汇报。批量 agent 任务同样有这个问题。
2. **streaming retry 硬禁用**：streaming 模式下 retry_badcase 被强制 False，没有 speculative retry（先 stream，如果最终超阈值再重生成并替换）。
3. **ZipEnhancer lazy init 不一致**：TextNormalizer 是 lazy init，ZipEnhancer 是 eager init（构造时就初始化）。两个可选组件策略不一致。
4. **StaticKVCache max_length 固定**：预分配全量显存（batch×heads×max_length×dim），不支持动态扩容。agent 的变长 context 需要动态 cache。
5. **i18n 实现是 inline dict**：`_I18N_TRANSLATIONS` 直接 hardcode 在 app.py，没有外部化。

---

## Adjacent Discoveries

- **MiniCPM4 LongRoPE**：`modules/minicpm4/model.py` 里的 `MiniCPMLongRoPE` 用 short_factor/long_factor 双 scale 处理短/长上下文，动态 NTK 缩放。比标准 RoPE 更适合变长 context 场景。
- **Snake1d 激活函数**：`audio_vae.py` 里用 `snake(x, alpha) = x + sin²(αx)/α`，`alpha` 是可学习参数。比 ReLU/SiLU 对周期性信号（音频）更友好，`@torch.jit.script` 加速。
- **CausalConv1d**：通过左 padding（`F.pad(x, (padding*2, 0))`）实现因果卷积，不修改 stride/dilation。比显式 mask 简洁。
- **CFG Zero-Star**：`unified_cfm.py` 里的 `solve_euler` 在初始 4% steps 用零向量替代，避免 CFG 早期的不稳定（对应 classifier-free guidance 的冷启动问题）。`optimized_scale` 用点积/范数比例动态调整 conditional/unconditional 权重。

---

## Meta Insights

1. **流水线的流式化 = 每个阶段独立 yield**。VoxCPM 的 streaming 不是在最外层 wrap 一个 generator，而是 `_inference` 内部在每个 decode step 就 yield。这让上层可以选择是 collect-all 还是 stream-forward，而不需要改内层逻辑。Orchestrator 的 dispatch pipeline 同样应该在最内层 yield，让外层决定聚合策略。

2. **Cache 分离两个关注点**：VoxCPM 的 prompt_cache 只存数据（audio_feat），不存计算状态（KV cache）。这是正确的分离——数据可以 pickle/serialize/跨进程传输，计算状态不行。Agent session context 的序列化应该只存 token sequence，不存 attention state。

3. **停止条件应该是可学习的**。VoxCPM 用一个 stop_head（2-class linear）替代 hardcode 的 EOS token 检测。这个 head 在训练时见过音频结束的分布，比 token-level EOS 更准。Agent loop 的 "何时停止" 同样可以用一个轻量 classifier 而非规则（max_steps、timeout、关键词匹配）。

4. **双轨残差架构的含义**：base_lm 做语义，residual_lm 在 base_lm 输出上做声学细化。两个 LM 的 hidden 加权后送进 DiT。这个模式（粗粒度模型 + 细粒度残差）可以用在 agent planning 上：快模型做 outline，慢模型做 detail fill-in，而不是一个模型做所有事。

5. **控制指令内联是 prompt engineering，不是架构**。`(control)text` 的括号前缀格式是训练时约定的，推理时直接使用。这提醒我们：给模型加"steering signal"的最简单方式往往是 prefix 约定，不需要额外 embedding 或 adapter。

---

## Implementation Status

3 P0 patterns implemented in commit `f8e1c13`:

| Pattern | File | What |
|---------|------|------|
| Generator cleanup (next_and_close) | `src/core/gen_cleanup.py`, `src/core/agent_client.py`, `src/governance/executor_session.py` | Wrap async generators in try/finally + aclose() to prevent resource leaks on early break (6 break paths in executor, exception paths in agent_client) |
| Prompt cache separation | `src/channels/chat/engine.py` | System prompt uses `cache_control: {"type": "ephemeral"}` — static per session, reused across multi-round tool-use (~90% cost savings on cached prefix) |
| BlockStreamer lookahead buffer | `src/channels/block_streamer.py`, `src/channels/config.py`, `src/channels/telegram/channel.py` | Adapted VoxCPM streaming_prefix_len overlap pattern — force-split searches configurable lookahead zone (200 chars) for natural break points before hard-cutting |

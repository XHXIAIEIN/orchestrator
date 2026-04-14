# R54 — RKNN-Toolkit2 Steal Report

**Source**: https://github.com/airockchip/rknn-toolkit2 | https://github.com/airockchip/rknn_model_zoo
**Stars**: toolkit2: 2,882 | model_zoo: 2,390
**License**: toolkit2: Proprietary (Rockchip) | model_zoo: Apache 2.0
**Date**: 2026-04-14
**Category**: Edge AI inference toolkit — model conversion pipeline + hardware-target registry

---

## TL;DR

RKNN-Toolkit2 is Rockchip's NPU compiler + runtime SDK for deploying neural networks on RK3588/RK3576/RV1106 edge chips. The steal target isn't the AI domain itself — it's the **structural patterns**: how they solve the same problems we face at the agent layer. Two transfers are high-value: (1) the **model conversion pipeline** as a template for agent task transformation pipelines, and (2) the **model zoo registry** as a template for declarative skill registries. The runtime C API also reveals clean patterns for resource lifecycle and context prioritization.

---

## Architecture Overview

### Repo Structure

```
rknn-toolkit2/
├── rknn-toolkit2/          # Python SDK (conversion + simulation)
│   ├── examples/
│   │   ├── onnx/           # Framework-specific conversion examples
│   │   ├── caffe/
│   │   ├── pytorch/
│   │   ├── tensorflow/
│   │   ├── tflite/
│   │   └── functions/      # Feature demonstrations
│   │       ├── accuracy_analysis/
│   │       ├── hybrid_quant/    # Two-phase quantization
│   │       ├── dynamic_shape/
│   │       ├── multi_batch/
│   │       ├── model_pruning/
│   │       ├── custom_op/
│   │       └── onnx_edit/
│   └── packages/           # Python wheel distributions
├── rknpu2/                  # C runtime library
│   ├── runtime/             # librknn_api (prebuilt .so)
│   │   └── Linux/librknn_api/include/rknn_api.h
│   └── examples/            # C demo programs
│       ├── rknn_mobilenet_demo/
│       ├── rknn_benchmark/
│       ├── rknn_dynamic_shape_input_demo/
│       ├── rknn_matmul_api_demo/
│       └── rknn_zero_copy/
├── rknn-toolkit-lite2/      # Lightweight Python runtime (device-side)
└── autosparsity/            # Sparse model training tool

rknn_model_zoo/
├── examples/               # 25+ model examples (YOLO, CLIP, Whisper, etc.)
│   └── <model_name>/
│       ├── python/
│       │   ├── convert.py       # Model conversion script
│       │   └── <model>.py       # Inference + evaluation
│       └── cpp/                 # C++ demo
├── py_utils/               # Shared executor abstraction
│   ├── rknn_executor.py
│   ├── onnx_executor.py
│   ├── pytorch_executor.py
│   └── coco_utils.py
└── datasets/
```

### Core API Lifecycle (Python SDK)

Every conversion follows the exact same 5-step pattern:

```python
rknn = RKNN(verbose=False)          # 1. Create context
rknn.config(                         # 2. Configure for target
    mean_values=...,
    std_values=...,
    target_platform='rk3588',
    dynamic_input=...,               # optional: multi-shape
    model_pruning=True,              # optional: sparse pruning
    quantized_algorithm='mmse',      # optional: quant algorithm
)
rknn.load_onnx(model=path)          # 3. Load source model
rknn.build(                          # 4. Compile + quantize
    do_quantization=True,
    dataset='./dataset.txt',
    rknn_batch_size=4,               # optional
)
rknn.export_rknn(output_path)        # 5. Emit artifact
rknn.init_runtime(target=...)        # 6. Init (if running locally)
outputs = rknn.inference(inputs=[img])
rknn.release()                       # 7. Cleanup
```

### Hybrid Quantization (Two-Phase Pipeline)

Advanced quantization splits into two files:

- `step1.py`: `rknn.hybrid_quantization_step1()` → emits `.model`, `.data`, `.quantization.cfg`
- (human edits `quantization.cfg` to mark which layers stay float)
- `step2.py`: `rknn.hybrid_quantization_step2(model_input, data_input, model_quantization_cfg)` → emits final `.rknn`

This is a checkpoint/resume pattern for long-running pipelines with human-in-the-loop checkpoints.

### Model Zoo Executor Abstraction

`py_utils/` provides a runtime-agnostic executor layer:

```python
def setup_model(args):
    if model_path.endswith('.pt'):
        from py_utils.pytorch_executor import Torch_model_container
        model = Torch_model_container(args.model_path)
    elif model_path.endswith('.rknn'):
        from py_utils.rknn_executor import RKNN_model_container
        model = RKNN_model_container(args.model_path, args.target, args.device_id)
    elif model_path.endswith('onnx'):
        from py_utils.onnx_executor import ONNX_model_container
        model = ONNX_model_container(args.model_path)
    return model, platform
```

All executors expose the same interface: `model.run(inputs)` + `model.release()`.

### C Runtime API (rknn_api.h)

The low-level C API reveals resource priorities and context flags:

```c
// Context priority flags
RKNN_FLAG_PRIOR_HIGH   = 0x00000000
RKNN_FLAG_PRIOR_MEDIUM = 0x00000001
RKNN_FLAG_PRIOR_LOW    = 0x00000002
RKNN_FLAG_ASYNC_MASK   = 0x00000004   // previous-frame result (pipeline mode)

// Memory flags
RKNN_FLAG_MEM_ALLOC_OUTSIDE      // caller manages memory
RKNN_FLAG_SHARE_WEIGHT_MEM       // weight-sharing across contexts
RKNN_FLAG_ENABLE_SRAM            // on-chip SRAM allocation
RKNN_FLAG_MODEL_BUFFER_ZERO_COPY // zero-copy model load

// NPU core targeting
RKNN_NPU_CORE_0    // single core
RKNN_NPU_CORE_0_1  // dual-core
RKNN_NPU_CORE_ALL  // auto-scale
```

Lifecycle: `rknn_init → rknn_query → rknn_inputs_set → rknn_run → rknn_outputs_get → rknn_outputs_release → rknn_destroy`

### Model Zoo Organization

25+ models organized by task category with consistent layout:

| Domain | Models |
|--------|--------|
| Detection | YOLOv5/v6/v7/v8/X, YOLO-World, YOLOv8-OBB, RetinaFace |
| Segmentation | YOLOv8-seg, DeepLabV3, PP-Seg, MobileSAM |
| Classification | MobileNet, ResNet |
| OCR | PPOCR (Det + Rec + System pipeline) |
| Audio | Whisper, wav2vec2, MMS-TTS, ZipFormer |
| Multimodal | CLIP (image + text encoders separate) |
| Pose | YOLOv8-pose |

Each model has: `convert.py` (conversion) + `<model>.py` (inference + evaluation + COCO mAP scoring).

### YAML Config Schema

The `model_config.yml` pattern provides declarative conversion config:

```yaml
models:
    name: resnet50v2
    platform: onnx
    model_file_path: ./resnet50v2.onnx
    quantize: true
    dataset: ./dataset.txt
    configs:
      quantized_dtype: asymmetric_quantized-8
      mean_values: [123.675, 116.28, 103.53]
      std_values: [58.82, 58.82, 58.82]
      quant_img_RGB2BGR: false
      quantized_algorithm: normal   # or mmse
      quantized_method: channel     # or layer
```

### Build System (Cross-compilation)

`build-linux.sh -t rk3588 -a aarch64 -d yolov8`:
- Auto-discovers demo by searching `examples/<name>/cpp/`
- Normalizes SOC variants (rk3566/rk3568 → rk356x)
- Outputs to `install/<platform>/<sdk>/`
- Validates presence of `.rknn` model post-install

---

## Steal Sheet

### Pattern 1: Immutable 5-Step Conversion Pipeline

**Source pattern**: config → load → build → export → (init_runtime + inference + release)

**Transfer target**: Agent task pipelines that transform inputs through fixed stages.

```python
# Current: ad-hoc per-skill setup
# Steal: explicit pipeline stages

class AgentPipeline:
    def configure(self, target: str, params: dict): ...    # target = 'dispatch'/'local'/'telegram'
    def load(self, task: Task): ...                         # validate + parse
    def build(self, context: Context): ...                  # plan + tool selection
    def export(self) -> Plan: ...                           # emit artifact before execution
    def execute(self) -> Result: ...                        # run with resources
    def release(self): ...                                  # cleanup: contexts, connections
```

The key insight: **export before execute**. RKNN always emits the compiled artifact (`.rknn` file) before running inference. We don't do this — we mix planning and execution. Separating `export()` (emit plan as artifact) from `execute()` (run plan) enables: plan review, resumability, plan caching, and rollback.

### Pattern 2: Runtime-Agnostic Executor with Unified Interface

**Source pattern**: `RKNN_model_container`, `ONNX_model_container`, `Torch_model_container` — all expose `.run(inputs)` + `.release()`.

**Transfer target**: Skill execution backends.

```python
# Current: skills are monolithic
# Steal: executor abstraction layer

class LocalExecutor:
    def run(self, task: Task) -> Result: ...
    def release(self): ...

class AgentSDKExecutor:
    def run(self, task: Task) -> Result: ...
    def release(self): ...

class TelegramBotExecutor:
    def run(self, task: Task) -> Result: ...
    def release(self): ...

def setup_executor(task_type: str, config: dict):
    if task_type == 'local':   return LocalExecutor(config)
    if task_type == 'sdk':     return AgentSDKExecutor(config)
    if task_type == 'tg':      return TelegramBotExecutor(config)
```

`setup_model()` in yolov8.py is basically our skill routing — but it returns a uniform interface. Our routing currently dispatches to completely different code paths. The uniform interface means evaluation, benchmarking, and error handling are shared.

### Pattern 3: Multi-Target Config as First-Class Parameter

**Source pattern**: `target_platform='rk3588'` is a config param that flows through the entire pipeline, determining compilation output, quantization method, memory layout, and runtime selection.

**Transfer target**: Agent task config carries `target` (environment/channel) as a first-class property:

```python
@dataclass
class TaskConfig:
    target: str          # 'prod' | 'staging' | 'local'
    channel: str         # 'tg' | 'slack' | 'direct'
    dtype: str           # 'async' | 'sync' | 'streaming'
    quantize: bool       # compression/token-limit mode
    dataset: str         # evaluation/test dataset path
```

Currently `target` leaks into individual skill implementations. Pull it up to config level.

### Pattern 4: Hybrid Pipeline = Human Checkpoint Between Automated Phases

**Source pattern**: `hybrid_quantization_step1()` emits intermediate artifacts → human edits config → `hybrid_quantization_step2()` resumes.

**Transfer target**: Long agent tasks with mandatory human review mid-pipeline:

```python
# Instead of one monolithic task:
result = agent.run(task)

# Hybrid checkpoint pattern:
checkpoint = agent.plan_phase1(task)
checkpoint.save('task_checkpoint.json')
# --- human reviews checkpoint.quantization_cfg ---
result = agent.execute_phase2(checkpoint)
```

This is exactly what we want for: code review → merge flows, spec → plan → implement flows, draft → approve → publish flows. The `.quantization.cfg` file is essentially the approval gate artifact.

### Pattern 5: Declarative Model Zoo = Declarative Skill Registry

**Source pattern**: Each model in `rknn_model_zoo/examples/<name>/` has:
- `model_config.yml` — declarative spec (platform, quantize, preprocessing params)
- `convert.py` — reproducible build script
- `<model>.py` — inference entry point with standard CLI args

**Transfer target**: Skill registry entries:

```yaml
# .claude/skills/<name>/skill_config.yml
skill:
    name: yolov8
    type: vision_detection
    executor: rknn           # or pytorch, onnx
    target: rk3588
    quantize: true
    input_shape: [640, 640]
    pre_process:
        mean: [0, 0, 0]
        std: [255, 255, 255]
    post_process: nms
    eval_dataset: coco_val2017
```

The pattern: every skill has a declarative config AND a reproducible build script AND an evaluation entry point. Currently our `SKILL.md` only covers the first. We're missing (b) and (c).

### Pattern 6: Composed Sub-Model Pipeline

**Source pattern**: `PPOCR-System` composes `TextDetector` → crop → `TextRecognizer` → filter. Each sub-model is independently initialized but orchestrated by a `TextSystem` wrapper that owns the pipeline.

```python
class TextSystem:
    def __init__(self, args):
        self.text_detector = predict_det.TextDetector(args)
        self.text_recognizer = predict_rec.TextRecognizer(args)
    
    def run(self, img):
        dt_boxes = self.text_detector.run(img)
        crops = [crop(img, box) for box in sorted_boxes(dt_boxes)]
        rec_res = self.text_recognizer.run(crops)
        return filter(rec_res, threshold=self.drop_score)
```

**Transfer target**: Multi-skill agent pipelines where each skill is independently testable but composed:

```python
class ResearchPipeline:
    def __init__(self):
        self.searcher = SearchSkill()
        self.summarizer = SummarizeSkill()
    
    def run(self, query: str) -> Report:
        results = self.searcher.run(query)
        return self.summarizer.run(results, threshold=self.confidence_threshold)
```

The `drop_score` threshold on `TextSystem` is the equivalent of our confidence/quality gates.

### Pattern 7: NPU Core Masking = Resource Allocation Flags

**Source pattern**: `RKNN_NPU_CORE_0`, `RKNN_NPU_CORE_0_1`, `RKNN_NPU_CORE_ALL` — callers specify compute allocation at context init time, not at runtime.

**Transfer target**: Agent context declares resource budget upfront:

```python
class AgentContext:
    core_mask: str = 'auto'    # 'single' | 'parallel' | 'all'
    priority: str = 'medium'   # 'high' | 'medium' | 'low'
    async_mode: bool = False    # pipeline mode (previous frame = previous task)
    mem_alloc: str = 'inside'   # 'inside' | 'outside' (caller-managed)
```

`RKNN_FLAG_ASYNC_MASK` is particularly interesting: in async mode the inference returns the *previous* frame's result, increasing throughput on single-threaded code. Direct analogue: streaming agent response returns previous step's result while current step computes — exactly what we want for block streaming.

### Pattern 8: Zero-Copy and SRAM Flags = Memory Budget Awareness

**Source pattern**:
- `RKNN_FLAG_MODEL_BUFFER_ZERO_COPY` — model already in NPU-accessible memory, skip copy
- `RKNN_FLAG_ENABLE_SRAM` + `RKNN_FLAG_SHARE_SRAM` — on-chip SRAM reuse across contexts
- `RKNN_FLAG_DISABLE_FLUSH_OUTPUT_MEM_CACHE` — skip CPU cache invalidation when output goes to GPU/RGA

**Transfer target**: Agent context budget flags:

```python
# Don't re-parse/re-embed context if already in working memory
AGENT_FLAG_CONTEXT_ZERO_COPY     = 0x01   # context already cached, skip re-read

# Share skill preloads across agents in same session
AGENT_FLAG_SHARE_SKILL_CACHE     = 0x02   # reuse loaded tool schemas

# Skip output formatting if output goes directly to next agent (not human)
AGENT_FLAG_DISABLE_FORMAT_OUTPUT = 0x04   # raw output → next stage, skip markdown
```

### Pattern 9: Autosparsity = Self-Optimization Hooks

**Source pattern**: `autosparsity` is a separate package that wraps PyTorch training with sparsity injection:

```python
from autosparsity.sparsity import sparsity_model
model = models.resnet50(pretrained=True).cuda()
sparsity_model(model, optimizer, mode)   # wraps model in-place, adds sparsity training
```

The model trains normally; `sparsity_model()` injects gradient hooks that push weights toward sparsity. After training, export → RKNN gets automatic `model_pruning` benefit.

**Transfer target**: Skill self-optimization hooks — instrument skill execution with quality signal capture, feed back to skill config:

```python
from orchestrator.autotune import tune_skill
skill = SearchSkill()
tune_skill(skill, quality_fn=retrieval_precision)   # wrap in-place with quality tracking
```

### Pattern 10: letter_box + get_real_box = Coordinate Transform Lifecycle

**Source pattern**: `COCO_test_helper` maintains a stateful transform chain:
- `letter_box(im, new_shape)` → pads and rescales, stores metadata
- `get_real_box(box)` → inverts the transform using stored metadata
- `get_real_seg(seg)` → same for segmentation masks

The state is accumulated as a list (`letter_box_info_list`), allowing batch evaluation with correct coordinate inversion.

**Transfer target**: Context compression and decompression — when context is compressed (letter-boxed), the compression metadata must be stored so decompression can recover original coordinates (token positions, document locations):

```python
class ContextCompressor:
    def compress(self, context, new_budget): ...   # stores compression metadata
    def decompress_citations(self, citations): ... # recovers original positions
```

---

## Comparison Matrix

| Dimension | RKNN Approach | Orchestrator Current | Gap |
|-----------|--------------|---------------------|-----|
| Pipeline stages | Explicit 5-phase API | Ad-hoc per-skill | Missing export-before-execute |
| Executor abstraction | Unified `.run()` + `.release()` | Divergent skill implementations | No unified interface |
| Target config | First-class `target_platform` param | Implicit per-skill | Target leaks into skill code |
| Human checkpoint | `hybrid_quant_step1/2` | None | No mid-pipeline approval pattern |
| Skill registry | YAML config + convert.py + eval | SKILL.md only | No declarative config or eval entry |
| Composed pipelines | TextSystem wraps Det+Rec | Skills are independent | No typed composition interface |
| Resource allocation | Flags at context init | None explicit | No resource declaration |
| Self-optimization | autosparsity hooks | Manual | No automatic quality injection |
| Accuracy analysis | Built-in `rknn.accuracy_analysis()` | Manual testing | No embedded eval method per skill |
| Multi-backend eval | COCO mAP built into every model | No standard eval | Skills not evaluable against benchmarks |

---

## Gaps

1. **No RKNN equivalent for LLM context**: The RKNN toolkit works because NPU computation is deterministic and byte-exact. LLM agents aren't — the "quantization" analogy breaks down for non-deterministic outputs. The `accuracy_analysis()` function has no analogue for agents (though we have evals).

2. **Target platform proliferation**: RKNN supports 10+ chip targets with per-target `.rknn` artifacts. Maintaining per-target builds is expensive. We face the same issue with per-channel skill variants (TG vs SDK vs local). The solution isn't more targets — it's a thinner hardware abstraction.

3. **The model_config.yml is duplicated work**: Every model has both code (`convert.py`) and config (`model_config.yml`). They can drift. We'd want a single source of truth — the config should be executable, or the code should be derivable from config.

4. **No registry index**: `rknn_model_zoo` has no `index.json` or programmatic catalog. Discovery is by filesystem traversal. A skill registry should have a queryable index with metadata (capability tags, input/output types, eval scores).

5. **C runtime vs Python SDK impedance**: The Python SDK runs on a dev machine; the C runtime runs on-device. There's an impedance mismatch — the `.rknn` artifact bridges them, but debugging across the boundary is painful. We have the same issue: our agent runs in Python but dispatched agents may run in different environments.

---

## Adjacent Discoveries

### Codegen Feature

`rknn-toolkit2/examples/functions/codegen/` — `rknn.export_rknn()` has a `export_soc_binaries_folder` option that emits C source code for the model's pre/post processing. The generated code is hardware-optimized and avoids Python overhead.

**Agent transfer**: Skill "compilation" — skills that run frequently could be compiled to more efficient forms. A skill executed 1000x/day is worth pre-compiling vs. interpreted-at-runtime. The `codegen` pattern says: interpret until hot, then compile.

### Custom Op Registration

`custom_op/` pattern: when a standard op isn't supported, register a custom kernel:

```python
from rknn.utils import onnx_edit
onnx_edit(model=..., inputs_transform={'k_cache.1': 'a,b,c,d->1,ad,b,c'})
```

**Agent transfer**: Custom tool registration — when standard tools can't handle a shape, define a transform adapter. The `inputs_transform` einsum notation is elegant: describe the reshape declaratively rather than coding it imperatively.

### `RKNN_FLAG_DUMMY_INIT` / Collect Model Info Only

`RKNN_FLAG_COLLECT_MODEL_INFO_ONLY` — init the context just to introspect the model (memory sizes, tensor shapes) without actually running anything.

**Agent transfer**: "Dry run" / capability query mode — before executing a plan, query what resources it would need:

```python
plan = agent.build(task, flags=AGENT_FLAG_COLLECT_INFO_ONLY)
print(plan.estimated_tokens, plan.required_tools, plan.execution_time_estimate)
```

### CLIP Dual-Encoder Split

`examples/clip/python/images/convert.py` + `text/convert.py` — the CLIP model's image and text encoders are converted separately as two `.rknn` files.

**Agent transfer**: Multi-modal tasks that have semantically separate "encoders" should be split into independently deployable units. A skill that does both retrieval and generation is two skills sharing a context — split them.

### Benchmark as First-Class Demo

`rknpu2/examples/rknn_benchmark/` — benchmarking is a built-in example, not an afterthought. Every SDK ships with a benchmark.

**Agent transfer**: Every skill should ship with a benchmark script in `constraints/benchmark.py`. "Ship the perf tool with the product."

### `perf_debug=True` + `eval_mem=True`

```python
ret = rknn.init_runtime(target=args.target, perf_debug=True, eval_mem=True)
rknn.eval_perf()    # prints per-layer timing
rknn.eval_memory()  # prints per-layer memory usage
```

These are runtime profiling flags. The per-layer breakdown (not just total) is the key — it lets you find the bottleneck layer.

**Agent transfer**: Per-step profiling for multi-step agent tasks — which step took longest, which used most context. We log at task level; we should log at step level.

---

## Meta Insights

**1. Compilation = Deferred Optimization**
The RKNN workflow forces a separation between *declaring intent* (config + load) and *executing intent* (build + export). The build step is where all optimization happens — quantization, pruning, hardware layout. The key insight is that optimization is not the author's job; it's the compiler's job. The author specifies *what* (target_platform, quantize, dtype); the compiler figures out *how*.

Applied to agents: skill authors should specify intent (input/output contract, quality bar); the orchestrator should figure out how to route, compress, parallelize. We've been conflating these. `SKILL.md` is both the intent spec and the execution impl.

**2. Quantization = Context Compression**
INT8 quantization is lossy compression — you trade accuracy for speed/size. The entire framework for managing this tradeoff (mmse algorithm, hybrid quant, accuracy_analysis) is directly analogous to context compression. We face the same tradeoff: compress context → faster / cheaper → less accurate reasoning. The RKNN toolkit has spent years building tooling around this tradeoff. We've barely started.

**3. Dataset.txt as Calibration Corpus**
Every quantized model needs a `dataset.txt` — a representative set of real inputs used to calibrate the quantization parameters. Without a good calibration set, quantization degrades accuracy badly.

Applied: every skill needs a calibration corpus — representative examples of what the skill will actually see in production. A skill calibrated on toy examples will perform differently on real inputs. This is exactly why eval datasets matter: not for testing, but for *calibrating* the skill's operating parameters.

**4. Target Platform Proliferation is a Tax**
Supporting 10 platforms (rk3562/3566/3568/3576/3588/rv1103/rv1106/rv1109/rv1126/rv1126b/rk1808) means 10 different compilation outputs, 10 different memory layouts, 10 driver versions to track. The build system normalizes this (rk3566 → rk356x), but the underlying complexity doesn't go away.

Applied: every new deployment target (new Telegram bot, new API endpoint, new user) is a new "platform". Platform proliferation is a real cost. The answer isn't "support everything" — it's "define a thin abstraction that maps M skills → N platforms" with the mapping table as first-class config.

**5. The Executor Container is the Right Abstraction Level**
`RKNN_model_container` / `ONNX_model_container` — the abstraction is at the *executor* level, not the *model* level or the *framework* level. The container owns: loading, running, releasing. The caller only sees `.run()`.

This is the right level for skill abstraction. Not "this is a Python function" (too low) and not "this is an AI agent" (too high). "This is an executor that takes inputs and produces outputs" — that's the right granularity.

"""
LLM Router — 统一路由层。
按 task_type 决定走 Ollama（本地）还是 Claude API SDK（云端）。
Ollama 失败自动 fallback 到 Claude。

Engine Waterfall 模式（偷自 Firecrawl）：
cascade 内的引擎并发竞速，第一个返回合格结果的赢。
超时后自动 waterfall 到下一个引擎，而不是等前一个跑完。
"""
import json
import logging
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

from src.core.llm_models import *  # noqa: F401,F403 — re-export all constants
from src.core.llm_models import (
    MODEL_SONNET, MODEL_HAIKU, MODEL_GEMMA_VISION,
    OLLAMA_HOST, MODEL_TIERS, ROUTES, MIN_RESPONSE_LEN,
    DEPTH_TIERS, DEFAULT_DEPTH, THRESHOLD_MODES, DEFAULT_THRESHOLD,
    GenerateResult, get_min_response_len,
    select_engine_by_features,
)
from src.core.llm_backends import (
    encode_images, ollama_generate, claude_generate, chrome_ai_generate,
)
from src.core.cost_tracking import CostTracker, CostLimitExceededError

log = logging.getLogger(__name__)


# ── Schema Complexity → Model Tier（偷自 Firecrawl）──
# 简单 schema 用便宜模型，复杂嵌套 schema 用强模型

_COMPLEXITY_TIERS = {
    "fast": 5,       # score 0-5: 最便宜/最快
    "balanced": 15,   # score 6-15: 平衡
    "strong": 999,    # score 16+: 最强
}


def _score_schema_complexity(schema: dict | None) -> int:
    """Score JSON schema complexity. Higher = needs stronger model.

    Scoring:
    - Each top-level field: +1
    - Nested object: +3 per level
    - Array of objects: +2
    - Enum constraints: +1
    - Required fields > 5: +2
    """
    if not schema:
        return 0

    score = 0
    properties = schema.get("properties", {})
    score += len(properties)

    required = schema.get("required", [])
    if len(required) > 5:
        score += 2

    for _prop_name, prop_def in properties.items():
        if not isinstance(prop_def, dict):
            continue
        prop_type = prop_def.get("type", "")
        if prop_type == "object":
            score += 3
            score += _score_schema_complexity(prop_def)
        elif prop_type == "array":
            items = prop_def.get("items", {})
            if isinstance(items, dict) and items.get("type") == "object":
                score += 2
                score += _score_schema_complexity(items)
        if "enum" in prop_def:
            score += 1

    return score


def select_model_for_schema(schema: dict | None) -> str:
    """Select appropriate model tier based on schema complexity.

    Returns tier name: "fast", "balanced", or "strong".
    """
    score = _score_schema_complexity(schema)

    if score <= _COMPLEXITY_TIERS["fast"]:
        return "fast"
    elif score <= _COMPLEXITY_TIERS["balanced"]:
        return "balanced"
    else:
        return "strong"


class ModelDegrader:
    """Track model success/failure and auto-degrade on consecutive failures.

    Pattern I12（偷自 OpenAkita）：滑动窗口追踪成功/失败比。
    3 consecutive failures → downgrade to cheaper model
    1 success after downgrade → restore original model
    """

    def __init__(self, window_size: int = 5, failure_threshold: int = 3):
        self._window: list[bool] = []  # True=success, False=failure
        self._window_size = window_size
        self._failure_threshold = failure_threshold
        self._degraded = False
        self._original_model: str | None = None

    def record(self, success: bool):
        """Record a generation result."""
        self._window.append(success)
        if len(self._window) > self._window_size:
            self._window.pop(0)

    def should_degrade(self) -> bool:
        """Check if we should switch to a cheaper model."""
        if self._degraded:
            return False
        if len(self._window) >= self._failure_threshold:
            tail = self._window[-self._failure_threshold:]
            if all(not s for s in tail):
                return True
        return False

    def should_restore(self) -> bool:
        """Check if we should restore the original model after degradation."""
        if not self._degraded:
            return False
        # 1 success after degradation → restore
        return len(self._window) > 0 and self._window[-1] is True

    @staticmethod
    def demote_model(model_name: str) -> str:
        """Pure function: return the next cheaper model name."""
        demotions = {
            "opus": "sonnet",
            "sonnet": "haiku",
            "haiku": "haiku",  # can't go lower
        }
        for key, val in demotions.items():
            if key in model_name.lower():
                return model_name.lower().replace(key, val)
        return model_name  # Unknown model, don't change

    def degrade(self, current_model: str) -> str:
        """Mark as degraded, return the fallback model name."""
        self._original_model = current_model
        self._degraded = True
        return self.demote_model(current_model)

    def restore(self) -> str | None:
        """Restore original model. Returns original model name or None."""
        if self._original_model:
            model = self._original_model
            self._degraded = False
            self._original_model = None
            self._window.clear()
            return model
        return None

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    def get_status(self) -> dict:
        # Count consecutive failures from the tail
        consecutive = 0
        for s in reversed(self._window):
            if not s:
                consecutive += 1
            else:
                break
        return {
            "degraded": self._degraded,
            "original_model": self._original_model,
            "recent_window": self._window[-5:],
            "consecutive_failures": consecutive,
        }


class LLMRouter:
    def __init__(self):
        self._ollama_available = None  # lazy probe
        self._tracker: CostTracker | None = None  # 可选：全链路成本追踪
        self._degrader = ModelDegrader()  # I12: 滑动窗口自动降级

    def set_tracker(self, tracker: CostTracker) -> None:
        """绑定一个 CostTracker，后续所有 generate 调用自动累计成本。"""
        self._tracker = tracker

    def clear_tracker(self) -> CostTracker | None:
        """解绑并返回当前 tracker（方便调用方拿走汇总）。"""
        t = self._tracker
        self._tracker = None
        return t

    @staticmethod
    def _estimate_cost(model_id: str, text: str) -> float:
        """估算单次调用的美元成本。基于 MODEL_TIERS.cost（$/M output tokens）。"""
        tier = MODEL_TIERS.get(model_id, {})
        cost_per_m = tier.get("cost", 0)
        if cost_per_m == 0:
            return 0.0
        # 粗估：1 token ≈ 4 chars（中文约 2 chars）
        est_tokens = max(len(text) / 3, 1)
        return round(cost_per_m * est_tokens / 1_000_000, 6)

    def generate(self, prompt: str, task_type: str,
                 max_tokens: int = 1024, temperature: float = 0.3,
                 images: list[str] | None = None,
                 depth: str = DEFAULT_DEPTH,
                 threshold: str = DEFAULT_THRESHOLD,
                 output_schema: dict | None = None,
                 features: dict | None = None,
                 feature_preference: str = "cost") -> str:
        """统一入口（向后兼容，返回纯文本）。"""
        return self.generate_rich(prompt, task_type, max_tokens, temperature,
                                   images, depth, threshold, output_schema,
                                   features, feature_preference).text

    def generate_rich(self, prompt: str, task_type: str,
                      max_tokens: int = 1024, temperature: float = 0.3,
                      images: list[str] | None = None,
                      depth: str = DEFAULT_DEPTH,
                      threshold: str = DEFAULT_THRESHOLD,
                      output_schema: dict | None = None,
                      features: dict | None = None,
                      feature_preference: str = "cost") -> GenerateResult:
        """Rich 入口 — 返回 GenerateResult，附带成本和诊断元数据。

        偷自 Exa costDollars：每次调用精确告诉调用方花了多少钱。
        偷自 Parallel usage：返回模型、延迟、尝试记录等诊断信息。

        output_schema: 可选 JSON Schema。提供时自动根据 schema 复杂度选模型档位
                       （偷自 Firecrawl schema-complexity routing）。
        """
        t0 = time.time()
        route = ROUTES.get(task_type)
        if not route:
            raise ValueError(f"Unknown task_type: {task_type}")

        warnings: list[str] = []
        model_used = ""
        attempts: list[dict] = []

        # ── I12: ModelDegrader — 降级时用 fallback 模型覆盖 cascade ──
        if self._degrader.is_degraded and self._degrader._original_model:
            warnings.append(f"model_degraded: original={self._degrader._original_model}")
            if "cascade" in route:
                degraded_cascade = [ModelDegrader.demote_model(m) for m in route["cascade"]]
                route = {**route, "cascade": degraded_cascade}
            elif "model" in route:
                route = {**route, "model": ModelDegrader.demote_model(route["model"])}

        # ── Feature Flag Engine Selection（偷自 Firecrawl feature-flag 矩阵）──
        # features 参数优先：按需求特征筛选引擎构建 cascade，而非走固定路由
        if features:
            selected = select_engine_by_features(
                required=features, preference=feature_preference)
            if selected:
                log.info(f"router: [features] {features} pref={feature_preference} "
                         f"-> {selected}")
                route = {**route, "cascade": selected}
            else:
                warnings.append(f"feature_select_empty: {features}, fallback to route default")
                log.warning(f"router: [features] no engine matches {features}, "
                            f"using route default")

        # ── Schema complexity → model tier override（偷自 Firecrawl）──
        # 仅在 route 有 cascade 且未被 force_claude/features 覆盖时生效
        if output_schema and "cascade" in route and not features:
            tier_name = select_model_for_schema(output_schema)
            _tier_model_map = {"fast": MODEL_HAIKU, "balanced": MODEL_SONNET, "strong": MODEL_SONNET}
            schema_model = _tier_model_map.get(tier_name, MODEL_HAIKU)
            score = _score_schema_complexity(output_schema)
            log.info(f"router: [schema] complexity={score} tier={tier_name} -> {schema_model}")
            # 用 schema 选出的模型替换 cascade，变成单引擎直连
            route = {**route, "cascade": [schema_model]}

        # ── depth 档位修正 ──
        tier = DEPTH_TIERS.get(depth, DEPTH_TIERS[DEFAULT_DEPTH])
        if tier["max_tokens_cap"] is not None:
            max_tokens = min(max_tokens, tier["max_tokens_cap"])
        # 复制 route 避免污染全局配置
        route = {**route, "timeout": max(5, int(route["timeout"] * tier["timeout_mult"]))}

        # 环境变量强制覆盖（cascade 路由也受此影响：跳过 cascade 直接走 Claude）
        force_claude = os.environ.get("LLM_FORCE_CLAUDE", "")
        if force_claude and task_type in [t.strip() for t in force_claude.split(",")]:
            log.info(f"router: [force_claude] {task_type} overridden to claude")
            model = route.get("model", route.get("cascade", [MODEL_HAIKU])[-1])
            if model.startswith("ollama/"):
                model = MODEL_HAIKU
            warnings.append(f"force_claude override: {task_type}")
            text = claude_generate(prompt, model, route["timeout"], max_tokens,
                                   encode_images(images) if images else None)
            model_used = model
        else:
            # 编码图片为 base64
            b64_images = encode_images(images) if images else None

            # 有 cascade 字段 → 走级联（depth 截断 cascade 长度）
            if "cascade" in route:
                text, model_used, attempts = self._generate_cascade(
                    prompt, route, max_tokens, temperature, b64_images, tier,
                    min_len=get_min_response_len(threshold))
            elif route["backend"] == "chrome-ai":
                model_id = f"chrome-ai/{route['model']}"
                result = chrome_ai_generate(prompt, model_id, max_tokens)
                if result and len(result) >= MIN_RESPONSE_LEN:
                    text, model_used = result, model_id
                elif route.get("fallback") == "claude":
                    fallback_model = route.get("fallback_model", MODEL_HAIKU)
                    log.info(f"router: chrome-ai {task_type} fallback -> {fallback_model}")
                    warnings.append(f"chrome-ai fallback to {fallback_model}")
                    text, model_used = claude_generate(
                        prompt, fallback_model, route["timeout"], max_tokens), fallback_model
                else:
                    text, model_used = result or "", model_id
            elif route["backend"] == "ollama":
                if route.get("no_think") and not prompt.rstrip().endswith("/no_think"):
                    prompt = prompt.rstrip() + "\n\n/no_think"
                text = self._ollama_with_fallback(
                    prompt, task_type, route, max_tokens, temperature, b64_images)
                model_used = f"ollama/{route['model']}"
            else:
                text = claude_generate(
                    prompt, route["model"], route["timeout"], max_tokens)
                model_used = route["model"]

        elapsed_ms = int((time.time() - t0) * 1000)
        cost = self._estimate_cost(model_used, text)

        # ── I12: ModelDegrader — 记录结果并检查降级/恢复 ──
        if text and len(text.strip()) >= MIN_RESPONSE_LEN:
            self._degrader.record(True)
            if self._degrader.should_restore():
                restored = self._degrader.restore()
                log.info(f"router: [degrader] model restored to {restored}")
                warnings.append(f"model_restored: {restored}")
        else:
            self._degrader.record(False)
            if self._degrader.should_degrade() and model_used:
                degraded_model = self._degrader.degrade(model_used)
                log.warning(f"router: [degrader] auto-degrading: {model_used} → {degraded_model}")
                warnings.append(f"model_auto_degraded: {model_used} → {degraded_model}")

        # ── CostTracker: 全链路成本累计（偷自 Firecrawl cost-tracking.ts）──
        if self._tracker and cost > 0:
            self._tracker.add_call(
                call_type=task_type, model=model_used, cost=cost,
                tokens={"est_out": max(int(len(text) / 3), 1)},
            )

        return GenerateResult(
            text=text,
            model_used=model_used,
            task_type=task_type,
            depth=depth,
            latency_ms=elapsed_ms,
            cost_dollars=cost,
            attempts=attempts,
            warnings=warnings,
        )

    # ── Waterfall 超时配置 ──
    # 每个引擎在这个时间后如果没返回，下一个引擎并发启动（而不是等它跑完）
    WATERFALL_DELAY_S = float(os.environ.get("LLM_WATERFALL_DELAY", "3.0"))

    def _call_one_model(self, model_id: str, prompt: str, route: dict,
                         max_tokens: int, temperature: float,
                         images: list[str] | None) -> tuple[str, str]:
        """调用单个模型，返回 (result_text, model_id)。失败抛异常。"""
        if model_id.startswith("chrome-ai/"):
            tier = MODEL_TIERS.get(model_id, {})
            if tier.get("env") == "desktop" and os.environ.get("BROWSER_HEADLESS", "false").lower() == "true":
                raise RuntimeError("headless_environment")
            result = chrome_ai_generate(prompt, model_id, max_tokens)
            return result or "", model_id

        if model_id.startswith("ollama/"):
            model_name = model_id.split("/", 1)[1]
            if self._ollama_available is False:
                raise RuntimeError("ollama_unavailable")
            p = prompt
            if route.get("no_think") and not p.rstrip().endswith("/no_think"):
                p = p.rstrip() + "\n\n/no_think"
            return ollama_generate(p, model_name, route["timeout"],
                                    max_tokens, temperature, images), model_id

        # Claude
        return claude_generate(prompt, model_id, route["timeout"],
                                max_tokens, images), model_id

    def _generate_cascade(self, prompt: str, route: dict,
                           max_tokens: int, temperature: float,
                           images: list[str] | None = None,
                           depth_tier: dict | None = None,
                           min_len: int = MIN_RESPONSE_LEN,
                           ) -> tuple[str, str, list[dict]]:
        """Engine Waterfall（偷自 Firecrawl）：并发竞速 + 超时降级。

        引擎按 cascade 顺序启动，但不等前一个跑完：
        - 第一个引擎立即启动
        - WATERFALL_DELAY_S 后如果没结果，下一个引擎并发启动
        - 第一个返回合格结果的赢，其余取消
        - 全部失败时走 retry（如果有预算）
        """
        cascade = list(route["cascade"])
        if depth_tier and depth_tier.get("max_cascade"):
            cascade = cascade[:depth_tier["max_cascade"]]
        retry_budget = (depth_tier or {}).get("retry", 0)
        attempts = []

        # 单引擎：直接调用，不走线程池
        if len(cascade) == 1:
            return self._try_single_model(
                cascade[0], prompt, route, max_tokens, temperature, images, min_len, attempts)

        # ── Waterfall：并发竞速 ──
        waterfall_delay = self.WATERFALL_DELAY_S
        result_text, result_model = "", ""

        with ThreadPoolExecutor(max_workers=len(cascade), thread_name_prefix="waterfall") as pool:
            futures: dict[Future, str] = {}  # future → model_id

            for i, model_id in enumerate(cascade):
                future = pool.submit(
                    self._call_one_model, model_id, prompt, route,
                    max_tokens, temperature, images,
                )
                futures[future] = model_id

                # 等 waterfall_delay 看当前批次有没有合格结果
                done_futures = set()
                try:
                    for done in as_completed(futures.keys() - done_futures, timeout=waterfall_delay):
                        done_futures.add(done)
                        mid = futures[done]
                        try:
                            text, _ = done.result(timeout=0)
                            if len(text.strip()) >= min_len:
                                log.info(f"router: [waterfall] {mid} won ({len(text)} chars, "
                                         f"stage={i+1}/{len(cascade)})")
                                result_text, result_model = text, mid
                                # 取消剩余 futures
                                for f in futures:
                                    if f not in done_futures:
                                        f.cancel()
                                return result_text, result_model, attempts
                            attempts.append({"model": mid, "reason": f"low_quality ({len(text.strip())} chars)"})
                        except Exception as e:
                            attempts.append({"model": mid, "reason": str(e)})
                except TimeoutError:
                    # waterfall 超时，启动下一个引擎（如果还有的话）
                    if i < len(cascade) - 1:
                        log.info(f"router: [waterfall] {model_id} timeout after {waterfall_delay}s, "
                                 f"launching {cascade[i+1]}")

            # 所有引擎都已启动，等待剩余结果
            for future in as_completed(futures.keys()):
                if result_text:
                    break
                mid = futures[future]
                try:
                    text, _ = future.result(timeout=route["timeout"])
                    if len(text.strip()) >= min_len:
                        log.info(f"router: [waterfall] late winner {mid} ({len(text)} chars)")
                        result_text, result_model = text, mid
                        break
                    attempts.append({"model": mid, "reason": f"low_quality ({len(text.strip())} chars)"})
                except Exception as e:
                    if {"model": mid, "reason": str(e)} not in attempts:
                        attempts.append({"model": mid, "reason": str(e)})

        if result_text:
            return result_text, result_model, attempts

        # 全部失败 — advanced 档位可重试最后一个模型
        if retry_budget > 0 and cascade:
            return self._retry_last(cascade[-1], prompt, route, max_tokens,
                                     temperature, images, min_len, attempts)

        log.warning(f"router: [waterfall] all engines failed: {attempts}")
        return "", "", attempts

    def _try_single_model(self, model_id, prompt, route, max_tokens, temperature,
                           images, min_len, attempts):
        """单引擎快速路径，不走线程池。"""
        try:
            text, mid = self._call_one_model(model_id, prompt, route,
                                              max_tokens, temperature, images)
            if len(text.strip()) >= min_len:
                log.info(f"router: [cascade] {mid} ok ({len(text)} chars)")
                return text, mid, attempts
            attempts.append({"model": mid, "reason": f"low_quality ({len(text.strip())} chars)"})
        except Exception as e:
            attempts.append({"model": model_id, "reason": str(e)})
        return "", "", attempts

    def _retry_last(self, last_model, prompt, route, max_tokens,
                     temperature, images, min_len, attempts):
        """重试最后一个模型。"""
        log.info(f"router: [waterfall] retry with {last_model}")
        try:
            text, mid = self._call_one_model(last_model, prompt, route,
                                              max_tokens, temperature, images)
            if len(text.strip()) >= min_len:
                log.info(f"router: [waterfall] retry success with {mid}")
                return text, mid, attempts
        except Exception as e:
            attempts.append({"model": last_model, "reason": f"retry_failed: {e}"})
        log.warning(f"router: [waterfall] all engines failed after retry: {attempts}")
        return "", "", attempts

    # ── Async Waterfall（偷自 Firecrawl Engine Waterfall）──
    # 给 asyncio 调用方提供原生协程版本，而不是强制走 ThreadPoolExecutor。
    # 与 _generate_cascade 互补：同步走线程池竞速，异步走 asyncio.wait。

    async def _waterfall_generate(
        self,
        engines: list[dict],
        prompt: str,
        delay_s: float | None = None,
        **kwargs,
    ) -> dict:
        """异步竞速多引擎，staggered start，第一个返回合格结果的赢。

        Args:
            engines: 引擎配置列表，每个: {"backend": str, "model": str, "timeout": int}
            prompt: 输入 prompt
            delay_s: 引擎间启动间隔（秒）。None = 使用 WATERFALL_DELAY_S 环境配置。
            **kwargs: 透传给 _generate_single_async

        Returns:
            {"text": str, "model": str, "attempts": list[dict]}

        Raises:
            RuntimeError: 所有引擎都失败时
        """
        import asyncio

        if delay_s is None:
            delay_s = self.WATERFALL_DELAY_S
        min_len = kwargs.pop("min_len", MIN_RESPONSE_LEN)
        attempts = []

        async def _try_engine(engine: dict, start_delay: float) -> dict:
            if start_delay > 0:
                await asyncio.sleep(start_delay)
            # 用线程跑同步的 _call_one_model（因为底层 HTTP 调用是同步的）
            loop = asyncio.get_running_loop()
            route = {"timeout": engine.get("timeout", 30), **kwargs}
            text, model_id = await loop.run_in_executor(
                None,
                self._call_one_model,
                engine["model"], prompt, route,
                kwargs.get("max_tokens", 1024),
                kwargs.get("temperature", 0.3),
                kwargs.get("images"),
            )
            if len(text.strip()) < min_len:
                raise ValueError(f"low_quality ({len(text.strip())} chars)")
            return {"text": text, "model": model_id}

        tasks = []
        for i, engine in enumerate(engines):
            task = asyncio.create_task(
                _try_engine(engine, delay_s * i),
                name=f"waterfall-{engine['model']}",
            )
            tasks.append(task)

        # 逐个收结果，第一个成功的赢
        winner = None
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t.cancelled():
                    continue
                exc = t.exception()
                if exc:
                    attempts.append({"model": t.get_name(), "reason": str(exc)})
                    continue
                winner = t.result()
                # 取消所有还在跑的
                for p in pending:
                    p.cancel()
                log.info(f"router: [async-waterfall] winner={winner['model']} "
                         f"({len(winner['text'])} chars)")
                return {**winner, "attempts": attempts}

        # 全部失败
        log.warning(f"router: [async-waterfall] all engines failed: {attempts}")
        raise RuntimeError(f"All waterfall engines failed: {attempts}")

    def _ollama_with_fallback(self, prompt: str, task_type: str, route: dict,
                               max_tokens: int, temperature: float,
                               images: list[str] | None = None) -> str:
        """尝试 Ollama，失败则 fallback 到 Claude。"""
        # 启动探测发现 Ollama 不可达 → 直接走 Claude（多模态路由无 fallback）
        if self._ollama_available is False:
            if route.get("fallback"):
                log.info(f"router: [skip_ollama] {task_type} -> claude (ollama unavailable)")
                return self._claude_fallback(prompt, task_type, route, max_tokens, images)
            log.warning(f"router: [skip_ollama] {task_type} failed (ollama unavailable, no fallback)")
            return ""

        t0 = time.time()
        try:
            result = ollama_generate(
                prompt, route["model"], route["timeout"], max_tokens, temperature, images
            )
            elapsed = time.time() - t0

            if len(result.strip()) < MIN_RESPONSE_LEN:
                if route.get("fallback"):
                    log.warning(f"router: [fallback] {task_type} ollama_garbage ({len(result.strip())} chars) -> claude")
                    return self._claude_fallback(prompt, task_type, route, max_tokens, images)
                log.warning(f"router: [error] {task_type} ollama_garbage ({len(result.strip())} chars), no fallback")
                return result

            log.info(f"router: [ollama] {task_type} {elapsed:.1f}s ok ({len(result)} chars)")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            reason = type(e).__name__
            if route.get("fallback"):
                log.warning(f"router: [fallback] {task_type} ollama_{reason} ({elapsed:.1f}s) -> claude")
                return self._claude_fallback(prompt, task_type, route, max_tokens, images)
            log.warning(f"router: [error] {task_type} ollama_{reason} ({elapsed:.1f}s), no fallback")
            return ""

    def _claude_fallback(self, prompt: str, task_type: str, route: dict,
                          max_tokens: int,
                          images: list[str] | None = None) -> str:
        """Fallback 到 Claude API（支持多模态）。"""
        fallback_model = route.get("fallback_model", MODEL_HAIKU)
        t0 = time.time()
        result = claude_generate(prompt, fallback_model, route["timeout"],
                                  max_tokens, images)
        elapsed = time.time() - t0
        log.info(f"router: [claude_fallback] {task_type} {elapsed:.1f}s ok")
        return result

    def check_ollama(self) -> bool:
        """探测 Ollama 是否可达 + 检查所需模型。启动时调用一次。"""
        try:
            url = f"{OLLAMA_HOST}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            log.info(f"router: Ollama reachable, models: {models}")
            # 检查路由表中需要的模型是否存在
            needed = {r["model"] for r in ROUTES.values() if r.get("backend") == "ollama"}
            for m in needed:
                if not any(m in avail for avail in models):
                    log.warning(f"router: Ollama model '{m}' not found, run: ollama pull {m}")
            self._ollama_available = True
            return True
        except Exception as e:
            log.warning(f"router: Ollama unreachable ({e}), all tasks will use Claude")
            self._ollama_available = False
            return False


# 模块级单例
_router = None

def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
        _router.check_ollama()
    return _router

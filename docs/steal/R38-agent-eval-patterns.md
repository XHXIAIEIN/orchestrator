# R38 — Agent Evaluation: Scoring, Sandboxing, Dataset & Reporting Patterns

Date: 2026-04-03
Sources: 15+ repos, 10+ papers, Anthropic/Google/Microsoft/LangChain official docs
Focus: How to evaluate sub-agents in an orchestrator system

---

## 1. Scoring Patterns

### 1.1 LLM-as-Judge (Model-Graded Evaluation)

**What**: Use a separate LLM to score agent output against criteria, replacing or augmenting human evaluation.

**Why it matters**: Manual evaluation doesn't scale. Human evals cost $5-50/task and take hours. LLM judges cost cents and run in seconds. Anthropic's guidance: start with 20-50 tasks from real failures, not synthetic benchmarks.

**State of the art (2025-2026)**:
- Anthropic's [Demystifying Evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents): Separate deterministic checks (tool selection, argument format) from LLM-judge checks (response quality, goal alignment). The outcome is the final state in the environment, not what the agent claims.
- [Bloom](https://github.com/safety-research/bloom) (Anthropic, open source): Four-stage pipeline — Understanding → Ideation → Rollout → Judgment. Judge models match human labels with Spearman r up to 0.86 across 16 frontier models. Key insight: the judge should see auto-generated diverse scenarios, not hand-picked ones.
- Microsoft [ai-agent-evals](https://github.com/microsoft/ai-agent-evals): GitHub Action that invokes agents, collects latency/token counts, runs model-judge evaluation, generates summary with confidence intervals. Supports multi-agent comparison against a baseline.

**Concrete implementation for Orchestrator**:
```python
# Extend eval_loop.py's EvalResult with model-graded scoring
@dataclass
class ModelGradedScore:
    dimension: str        # e.g. "correctness", "safety", "completeness"
    score: float          # 0-1 normalized
    confidence: float     # judge's self-assessed confidence
    reasoning: str        # chain-of-thought from judge
    judge_model: str      # which model judged

class EvalResult:  # extend existing
    model_grades: list[ModelGradedScore] = field(default_factory=list)

    @property
    def weighted_score(self) -> float:
        """Confidence-weighted average across dimensions."""
        if not self.model_grades:
            return 0.0
        total_w = sum(g.confidence for g in self.model_grades)
        if total_w == 0:
            return 0.0
        return sum(g.score * g.confidence for g in self.model_grades) / total_w
```

Judge prompt should be **task-specific**, not generic. Include:
1. Task description (what was asked)
2. Agent output (what was produced)
3. Ground truth or reference (if available)
4. Explicit rubric (scoring criteria with examples per level)

**Anti-patterns**:
- Self-review (same agent evaluating its own work) — already captured in `evaluator_fix_loop.md`
- Context bleeding (judge sees full conversation, not just diff + task)
- Using same model family for judge and executor — reduces diversity of failure detection

---

### 1.2 Multi-Evaluator Consensus

**What**: Multiple judges score independently, then aggregate via voting, debate, or adversarial challenge.

**Why it matters**: Single LLM judges have known biases — position bias (preferring first/last items), verbosity bias (longer = better), self-enhancement bias (preferring own model family). Multi-judge consensus reduces all three.

**Key frameworks (2025)**:

**CourtEval** (ACL 2025): Courtroom metaphor with three roles:
1. **Grader** (Judge): Assigns initial score
2. **Critic** (Prosecutor): Argues why score is wrong
3. **Defender** (Attorney): Counters the Critic
4. **Grader** re-evaluates after hearing both sides

This adversarial process outperforms single-judge on SummEval and TopicalChat benchmarks.

**MAJ-EVAL**: Auto-constructs evaluator personas by extracting dimensions from domain documents. Each dimension becomes a distinct agent persona. Multi-agent trait-based approaches achieve higher correlation than single-LLM baselines.

**Implementation for Orchestrator**:
```python
class ConsensusEvaluator:
    """Three-judge panel with adversarial challenge."""

    async def evaluate(self, task_desc: str, agent_output: str) -> EvalResult:
        # Phase 1: Independent scoring (parallel)
        scores = await asyncio.gather(
            self._judge(model="claude-sonnet", task_desc=task_desc, output=agent_output),
            self._judge(model="gpt-4o", task_desc=task_desc, output=agent_output),
            self._judge(model="claude-haiku", task_desc=task_desc, output=agent_output),
        )

        # Phase 2: Check agreement
        if self._high_agreement(scores):
            return self._aggregate(scores)

        # Phase 3: Adversarial challenge on disagreements
        challenged = await self._courteval_challenge(scores, task_desc, agent_output)
        return self._aggregate(challenged)

    def _high_agreement(self, scores: list) -> bool:
        """Agreement if all scores within 0.15 of each other."""
        values = [s.weighted_score for s in scores]
        return max(values) - min(values) < 0.15
```

**When to use**: Reserve multi-judge for high-stakes decisions (promoting patterns to boot.md, passing HARD gate fitness checks). For routine task evaluation, single judge + deterministic checks is sufficient.

---

### 1.3 Rubric-Based Scoring with Partial Credit

**What**: Define structured rubrics with weighted criteria, each allowing partial credit (not just pass/fail).

**Why it matters**: Binary pass/fail loses information. An agent that got 4/5 steps right but failed the last one should score differently from one that failed immediately. Partial credit enables gradient-based improvement.

**Key research (2025-2026)**:

**AdaRubric** (arxiv:2603.21362): Task-adaptive rubrics generated on-the-fly from task descriptions. Achieves Pearson r=0.79 with human correlation (+0.16 over best static baseline). Key innovation: **DimensionAwareFilter** prevents high-scoring dimensions from masking failures in others.

**RULERS** (arxiv:2601.08654): Evidence-anchored scoring — each score must cite specific evidence from the output. Prevents judges from "vibe-scoring."

**AutoSCORE**: Two-agent system — one extracts rubric components, the other scores. Ensures rubric alignment.

**Ternary grading**: {Satisfied, Partially Satisfied, Not Satisfied} per criterion. Final score = weighted sum. Works better than 5-point scales for LLM judges (less noise).

**Implementation for Orchestrator**:
```python
@dataclass
class RubricCriterion:
    name: str
    weight: float           # 0-1, must sum to 1 across criteria
    description: str
    satisfied: str          # example of full credit
    partial: str            # example of partial credit
    not_satisfied: str      # example of zero credit

@dataclass
class RubricScore:
    criterion: str
    verdict: Literal["satisfied", "partial", "not_satisfied"]
    evidence: str           # specific text from output justifying score
    score: float            # 1.0 / 0.5 / 0.0

def generate_task_rubric(task_description: str) -> list[RubricCriterion]:
    """AdaRubric-style: generate criteria from task description.

    For code tasks: [correctness, error_handling, style_match, test_coverage]
    For research tasks: [coverage, accuracy, source_quality, synthesis]
    For conversation tasks: [goal_alignment, tone, completeness]
    """
    # LLM call to generate task-specific rubric
    ...
```

**Integration with existing eval_loop.py**: The current `IssueSeverity` (INFO/LOW/HIGH/CRITICAL) maps naturally to rubric scores. Add rubric output as a parallel scoring dimension alongside the existing issue-based evaluation.

---

### 1.4 Trajectory/Process Evaluation

**What**: Score the agent's decision-making process (tool calls, reasoning steps, backtracking), not just the final answer.

**Why it matters**: Two agents can reach the same correct answer, but one took 3 efficient steps while the other thrashed through 15 unnecessary tool calls. Process quality predicts reliability. An agent that gets lucky once will fail next time.

**Key frameworks**:

**LangChain AgentEvals** ([github](https://github.com/langchain-ai/agentevals)): Framework-agnostic trajectory evaluation from OpenTelemetry traces. Three match modes:
- **strict**: Identical messages in same order with same tool calls
- **superset**: Output trajectory is valid if it's a superset of reference
- **LLM-as-judge**: Uses `TRAJECTORY_ACCURACY_PROMPT` to evaluate quality

**Google Cloud** [Methodical Agent Evaluation](https://cloud.google.com/blog/topics/developers-practitioners/a-methodical-approach-to-agent-evaluation): Three-layer approach:
1. **Component-level**: Each tool call evaluated independently
2. **Trajectory-level**: Sequence of decisions evaluated for efficiency and correctness
3. **Session-level**: Overall goal completion across multi-turn interactions

**AWS Bedrock AgentCore**: GA in 2025, handles evaluation models/inference/data pipelines at scale.

**Strands Agents**: Built-in trajectory evaluator that scores action sequences against expected behavior patterns.

**Implementation for Orchestrator**:
```python
@dataclass
class TrajectoryStep:
    action: str             # "tool_call", "reasoning", "delegation"
    detail: str             # what specifically happened
    timestamp: float
    token_cost: int
    was_necessary: bool     # post-hoc judgment

@dataclass
class TrajectoryScore:
    efficiency: float       # optimal_steps / actual_steps
    correctness: float      # steps that were correct / total steps
    recovery: float         # did agent recover from mistakes?
    tool_selection: float   # right tool for the job?

    @property
    def composite(self) -> float:
        return (self.efficiency * 0.2 + self.correctness * 0.4 +
                self.recovery * 0.2 + self.tool_selection * 0.2)
```

**Integration with Governor**: The Governor's `_dispatch_quality_review` already produces an ACT→EVAL loop. Adding trajectory scoring means capturing each step's tool calls and reasoning, then scoring the sequence post-hoc. Store trajectories in the learnings DB for pattern mining.

---

### 1.5 Tool Use Quality Scoring

**What**: Specifically evaluate how well the agent selects and uses available tools.

**Why it matters**: Tool selection is the most concrete, measurable aspect of agent behavior. Wrong tool = wasted tokens + wrong answer. Redundant tool calls = cost explosion.

**Metrics**:
- **Tool Selection Accuracy**: Did the agent pick the right tool? (deterministic check against reference)
- **Argument Quality**: Were the tool arguments correct and complete?
- **Tool Efficiency**: Could the same result be achieved with fewer calls?
- **Error Recovery**: When a tool call fails, does the agent retry appropriately?
- **Tool Discovery**: Does the agent find and use tools it hasn't been explicitly told about?

**Implementation**:
```python
@dataclass
class ToolUseScore:
    selection_accuracy: float   # correct tool / total tool calls
    argument_quality: float     # well-formed args / total calls
    efficiency: float           # min_needed_calls / actual_calls
    error_recovery: float       # recovered_errors / total_errors
    unnecessary_calls: int      # tool calls that added no information

def score_tool_use(trajectory: list[TrajectoryStep],
                   available_tools: list[str],
                   reference_trajectory: list[TrajectoryStep] | None = None) -> ToolUseScore:
    """Score tool use quality from a completed trajectory."""
    ...
```

---

### 1.6 Self-Consistency Checks

**What**: Run the same task multiple times and measure variance in outputs. Consistent results indicate reliable knowledge; inconsistent results indicate hallucination or randomness.

**Why it matters**: LLM agents are stochastic. A single eval run can be lucky or unlucky. Self-consistency separates genuine capability from random success.

**Key research**:

**SelfCheckGPT**: Hallucinated outputs aren't reproducible. Sample multiple responses; if facts are consistent across samples, they're likely real knowledge. If they vary, it's likely hallucination.

**CISC** (ACL 2025, [github](https://github.com/taubenfeld/CISC)): Confidence-Informed Self-Consistency. Weighted majority vote based on model's self-assessed confidence. Outperforms standard self-consistency in nearly all configurations. Reduces required reasoning paths by 40%+ on average. With just 8 samples, surpasses 30-sample standard self-consistency.

Three confidence extraction methods:
1. **Response Probability**: Normalized log-prob of the reasoning path
2. **Verbal Confidence**: Model states its confidence in natural language
3. **P(True)**: Model estimates probability its answer is correct

**Evaluating Evaluator Consistency** (COLING 2025): Even strong proprietary models aren't necessarily consistent evaluators. Two dimensions: Self-Consistency (same input → same score) and Inter-scale Consistency (different scoring scales → same relative ranking).

**Implementation for Orchestrator**:
```python
async def consistency_check(task: str, agent_fn, n_runs: int = 5) -> dict:
    """Run same task N times, measure output consistency."""
    results = [await agent_fn(task) for _ in range(n_runs)]

    # Extract key facts from each result
    facts_per_run = [extract_key_facts(r) for r in results]

    # Count fact frequency across runs
    fact_counts = Counter(f for facts in facts_per_run for f in facts)

    # Facts appearing in >80% of runs = likely reliable
    reliable_facts = {f for f, c in fact_counts.items() if c / n_runs > 0.8}
    unreliable_facts = {f for f, c in fact_counts.items() if c / n_runs < 0.4}

    return {
        "consistency_score": len(reliable_facts) / max(len(fact_counts), 1),
        "reliable_facts": reliable_facts,
        "unreliable_facts": unreliable_facts,  # likely hallucinations
        "variance": _compute_output_variance(results),
    }
```

**When to use in Orchestrator**: Run consistency checks on agent responses that will be promoted to boot.md or used as training data for other agents. Don't run on every task — it's N× the cost.

---

## 2. Sandboxing Patterns

### 2.1 Docker-Based Eval Sandboxes

**What**: Run agent evaluation in Docker containers with controlled environments.

**Why it matters**: Agents that execute code, modify files, or make network calls need isolation. Without sandboxing, a bad eval run can corrupt the host system.

**Critical insight from 2025 consensus**: **Docker is not a sandbox.** Docker containers share the host kernel. A container escape vulnerability gives full host access. Docker is sufficient for *reproducibility* (consistent environment) but not for *security* (untrusted code isolation).

**What Docker IS good for in eval**:
- Reproducible environments (same deps, same OS)
- File system snapshots (reset state between eval runs)
- Resource limits (memory/CPU caps)
- Network namespace isolation (basic)

**Implementation for Orchestrator**:
```yaml
# docker-compose.eval.yml
services:
  eval-sandbox:
    build: ./eval
    mem_limit: 2g
    cpus: 1.0
    network_mode: "none"          # no network by default
    read_only: true               # immutable root filesystem
    tmpfs:
      - /tmp:size=512m            # writable scratch space
    volumes:
      - ./eval-tasks:/tasks:ro    # read-only task inputs
      - eval-output:/output       # write-only output
    security_opt:
      - no-new-privileges:true
    pids_limit: 100               # prevent fork bombs
```

**For our use case**: Docker is fine for now. We're evaluating our own sub-agents, not arbitrary untrusted code. The threat model is "agent does something dumb" not "agent actively attacks the host."

---

### 2.2 MicroVM Sandboxes (Firecracker / gVisor)

**What**: Hardware-level isolation using lightweight VMs instead of containers.

**Why it matters**: When you need true isolation — each sandbox gets its own kernel. Container escapes become meaningless because there's nothing to escape to.

**Two dominant approaches (2025-2026)**:

**Firecracker MicroVMs** (used by E2B, AWS Lambda):
- Own kernel per workload
- 3-5 MB memory overhead per instance
- Boot in ≤125ms (from snapshot), ~160-180ms end-to-end
- E2B processes 15M+ sandbox sessions/month with this tech
- Manus AI uses E2B for "virtual computers" for their agents

**gVisor** (used by Google GKE, Kubernetes Agent Sandbox):
- User-space kernel that intercepts syscalls before they reach host kernel
- Less isolation than Firecracker (shared host kernel, but syscall-filtered)
- Lower overhead, no separate kernel boot
- Google's [Agent Sandbox](https://github.com/kubernetes-sigs/agent-sandbox) for K8s: declarative API for managing isolated pods with warm pools for sub-second startup

**When to upgrade from Docker**: If/when the orchestrator starts executing untrusted code from external sources, or if eval tasks involve running code that could have side effects beyond the file system.

---

### 2.3 File System Isolation

**What**: Control what the agent can see and modify during evaluation.

**Patterns**:

1. **Copy-on-Write Snapshots**: Start each eval from a known filesystem state. Use overlayfs or Btrfs snapshots.
```bash
# Create eval workspace from template
mkdir -p /eval/run-${RUN_ID}
mount -t overlay overlay -o lowerdir=/eval/template,upperdir=/eval/run-${RUN_ID}/upper,workdir=/eval/run-${RUN_ID}/work /eval/run-${RUN_ID}/merged
```

2. **Read-Only Task Inputs**: Agent can read task files but not modify them.

3. **Monitored Output Directory**: All agent writes go to a single output directory. Post-eval, compare output against expected.

4. **Git Worktrees**: Already used in Orchestrator (`data/worktrees/task-*`). Each task gets an isolated worktree. Perfect for code modification tasks.

**Orchestrator already does this well** — the worktree pattern in `data/worktrees/` is solid file system isolation. Enhancement: add checksums of input files before/after to detect unauthorized modifications.

---

### 2.4 Network Isolation with Controlled Access

**What**: Control which network resources the agent can access during evaluation.

**Patterns**:
- **Full isolation** (`network_mode: none`): No network at all. Strictest.
- **Allowlist proxy**: Route all traffic through a proxy that only allows specific domains.
- **DNS-based filtering**: Custom DNS that only resolves allowed domains.
- **Network policy** (K8s): Fine-grained ingress/egress rules per pod.

```python
# Eval-time network policy
EVAL_NETWORK_POLICY = {
    "allow_dns": True,
    "allowed_domains": [
        "api.anthropic.com",   # for LLM calls only
        "api.openai.com",
    ],
    "blocked_domains": ["*"],  # block everything else
    "max_egress_bytes": 10_000_000,  # 10MB cap
    "timeout_seconds": 30,
}
```

---

### 2.5 Timeout and Resource Limits

**What**: Prevent runaway evaluations from consuming infinite resources.

**Patterns**:
```python
@dataclass
class EvalResourceLimits:
    max_wall_time: int = 300          # 5 minutes per task
    max_cpu_time: int = 120           # 2 minutes CPU
    max_memory_mb: int = 2048         # 2GB RAM
    max_tokens_in: int = 100_000      # input token budget
    max_tokens_out: int = 50_000      # output token budget
    max_tool_calls: int = 50          # prevent infinite tool loops
    max_llm_calls: int = 20           # cap API calls
    max_file_writes: int = 100        # cap file system modifications
    max_output_size_mb: int = 50      # cap total output size

    def check_budget(self, current: "ResourceUsage") -> bool:
        """Return False if any limit exceeded."""
        ...
```

**Integration**: The existing `LoopState.max_iterations = 3` in `eval_loop.py` is a form of resource limiting. Extend to cover token/time budgets.

---

## 3. Dataset Management Patterns

### 3.1 Eval Dataset Versioning

**What**: Version-control evaluation datasets so results are reproducible across time.

**Why it matters**: If you change the eval dataset and scores go up, did the agent improve or did you make the test easier?

**Approaches**:
- **Git-based**: Store eval datasets in repo, tag each version. Braintrust links every eval run to exact dataset version.
- **Content-addressed**: Hash dataset contents, store hash with results. Any change = new version.
- **Schema-versioned**: Separate schema version from data version. Schema v2 can contain v1 data.

**Implementation**:
```python
@dataclass
class EvalDataset:
    version: str                      # semantic version
    content_hash: str                 # SHA256 of all task data
    tasks: list[EvalTask]
    created_at: datetime
    parent_version: str | None        # for tracking lineage

    @classmethod
    def from_directory(cls, path: str) -> "EvalDataset":
        tasks = load_tasks(path)
        content = json.dumps([t.to_dict() for t in tasks], sort_keys=True)
        return cls(
            version=_next_version(path),
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            tasks=tasks,
            created_at=datetime.now(),
            parent_version=_current_version(path),
        )
```

---

### 3.2 Contamination Detection

**What**: Detect when the model being evaluated has seen the test data during training.

**Why it matters**: If the model memorized the answers, the eval is worthless. This is a growing problem as models train on more internet data.

**Approaches (2025)**:
- **CoDeC (Contamination Detection via Context)**: Measures how in-context learning affects performance. If giving context helps a lot, the model probably hasn't memorized the answer. If context barely helps, it might have.
- **Log-probability gaps**: Compare log-probs of known training data vs held-out data. Gap = contamination signal. Caveat: PPO-style RL can hide this signal.
- **First-hop accuracy drops**: 5-15% accuracy drops on first transformation of benchmark data indicate contamination of original form.

**For Orchestrator sub-agent eval**: Less relevant since we're testing task execution, not factual knowledge. But matters if we test agents on coding benchmarks — verify the benchmark hasn't been in training data.

**Practical approach**: Generate fresh eval tasks from templates with random parameters. A contaminated model can't memorize parametric variations.

---

### 3.3 Dynamic/Generative Test Cases

**What**: Generate eval tasks programmatically rather than maintaining static datasets.

**Why it matters**: Static benchmarks get saturated. Models optimize for specific test cases. Dynamic generation ensures each eval run is fresh.

**Approaches**:
- **Parameterized templates**: Define task structure with variable parameters.
- **LLM-generated tasks**: Use a separate LLM to generate evaluation tasks (Bloom's approach).
- **Difficulty curves**: Parameterize difficulty (e.g., number of reasoning hops, code complexity).
- **Adversarial generation**: Generate tasks that target known weaknesses.

**Implementation**:
```python
class TaskGenerator:
    """Generate fresh eval tasks from templates."""

    templates = {
        "code_fix": {
            "base": "Fix the bug in this {language} function that {bug_type}",
            "params": {
                "language": ["python", "javascript", "rust"],
                "bug_type": ["off-by-one", "null reference", "type mismatch",
                             "race condition", "memory leak"],
            },
            "difficulty_axis": "code_complexity",  # lines of code, nesting depth
        },
        "research": {
            "base": "Find {n} sources about {topic} and synthesize findings",
            "params": {
                "n": [3, 5, 8],
                "topic": _load_topic_pool(),
            },
            "difficulty_axis": "topic_obscurity",
        },
    }

    def generate(self, template_name: str, difficulty: float = 0.5,
                 n_tasks: int = 10) -> list[EvalTask]:
        """Generate n_tasks at specified difficulty level."""
        ...
```

**For Orchestrator**: Use Bloom's approach — define the behavior to test, auto-generate diverse scenarios. Already have the Clawvard exam infrastructure; extend it with generative task creation.

---

### 3.4 Difficulty Calibration

**What**: Ensure eval tasks span a meaningful difficulty range and are calibrated against known baselines.

**Approaches**:
- **Human baseline collection**: Have humans attempt the same tasks. Agent scores relative to human baseline.
- **Multi-model calibration**: Run the same tasks across multiple models. If all models ace it, the task is too easy. If none pass, it might be broken (not hard).
- **Progressive difficulty**: Start easy, increase difficulty until failure rate reaches target (e.g., 50% pass rate = well-calibrated).

```python
def calibrate_difficulty(tasks: list[EvalTask], models: list[str]) -> list[EvalTask]:
    """Assign difficulty scores based on multi-model pass rates."""
    for task in tasks:
        pass_rates = {}
        for model in models:
            results = [run_task(task, model) for _ in range(5)]
            pass_rates[model] = sum(r.passed for r in results) / len(results)

        avg_pass = sum(pass_rates.values()) / len(pass_rates)
        task.difficulty = 1.0 - avg_pass  # 0=trivial, 1=impossible
        task.calibration_data = pass_rates

    return tasks
```

---

## 4. Reporting Patterns

### 4.1 Eval Dashboards and Visualization

**What**: Visual interface for tracking eval results over time.

**Key platforms (2025-2026)**:
- **Braintrust** ($80M raise, $800M valuation): Dataset management + scoring + experiment tracking + CI enforcement in single platform. Every run linked to exact prompt version, model, and dataset.
- **Langfuse** (open source, self-hosted): Trace visualization, prompt versioning, LLM-as-judge, cost/latency tracking. Uses ClickHouse + OpenTelemetry.
- **DeepEval** (open source): pytest-compatible LLM testing. Strong for CI/CD integration.
- **Arize Phoenix**: Production observability with eval integration.

**For Orchestrator dashboard**: We already have a dashboard at :23714. Add an eval tab with:
```
- Score trend chart (per-agent, over time)
- Per-dimension breakdown (correctness, efficiency, tool use, style)
- Cost tracking (tokens per eval run)
- Failure pattern clustering (which types of tasks fail most?)
- Recent eval runs table with drill-down to individual task results
```

---

### 4.2 Regression Detection

**What**: Automatically detect when agent performance drops compared to a baseline.

**Implementation**:
```python
@dataclass
class RegressionAlert:
    metric: str
    baseline_value: float
    current_value: float
    delta: float
    is_significant: bool     # statistical test result
    p_value: float

def detect_regression(
    current_scores: list[float],
    baseline_scores: list[float],
    threshold: float = 0.05,   # minimum meaningful delta
    alpha: float = 0.05,       # significance level
) -> RegressionAlert | None:
    """Bootstrap test for regression detection."""
    current_mean = statistics.mean(current_scores)
    baseline_mean = statistics.mean(baseline_scores)
    delta = current_mean - baseline_mean

    if abs(delta) < threshold:
        return None  # Not meaningful

    # Bootstrap confidence interval
    n_bootstrap = 10000
    diffs = []
    combined = current_scores + baseline_scores
    n_current = len(current_scores)
    for _ in range(n_bootstrap):
        sample = random.choices(combined, k=len(combined))
        boot_current = statistics.mean(sample[:n_current])
        boot_baseline = statistics.mean(sample[n_current:])
        diffs.append(boot_current - boot_baseline)

    diffs.sort()
    ci_lower = diffs[int(n_bootstrap * alpha / 2)]
    ci_upper = diffs[int(n_bootstrap * (1 - alpha / 2))]

    # Significant if CI doesn't contain 0
    is_significant = (ci_lower > 0 and delta > 0) or (ci_upper < 0 and delta < 0)

    if delta < 0 and is_significant:
        return RegressionAlert(
            metric="composite_score",
            baseline_value=baseline_mean,
            current_value=current_mean,
            delta=delta,
            is_significant=True,
            p_value=sum(1 for d in diffs if d <= delta) / n_bootstrap,
        )
    return None
```

**Integration with existing `LoopState.get_trend()`**: The current trend tracking (improving/stalled/worsening) is qualitative. Add quantitative regression detection with bootstrap CIs.

---

### 4.3 Confidence Intervals and Statistical Significance

**What**: Report uncertainty alongside scores so small sample sizes don't mislead.

**Why it matters**: "Agent A scores 85% vs Agent B at 82%" means nothing without sample size and variance. With n=10 tasks, that could easily be noise.

**Spark-LLM-Eval** ([github](https://github.com/bassrehab/spark-llm-eval)): Distributed evaluation framework with built-in bootstrap CIs and significance testing. Spark-native for large-scale evaluation.

**Microsoft ai-agent-evals**: When comparing multiple agents, automatically includes confidence intervals and statistical comparison against baseline.

**Minimum viable implementation**:
```python
def score_with_confidence(scores: list[float], confidence: float = 0.95) -> dict:
    """Return mean score with bootstrap confidence interval."""
    n_bootstrap = 5000
    means = []
    for _ in range(n_bootstrap):
        sample = random.choices(scores, k=len(scores))
        means.append(statistics.mean(sample))
    means.sort()

    alpha = 1 - confidence
    return {
        "mean": statistics.mean(scores),
        "ci_lower": means[int(n_bootstrap * alpha / 2)],
        "ci_upper": means[int(n_bootstrap * (1 - alpha / 2))],
        "n": len(scores),
        "std": statistics.stdev(scores) if len(scores) > 1 else 0,
    }
```

---

### 4.4 Per-Capability Breakdown

**What**: Report scores broken down by capability dimension, not just an aggregate.

**Why it matters**: Aggregate "82% score" hides the fact that the agent is 95% on code tasks and 40% on research tasks. Per-capability breakdown guides targeted improvement.

**Implementation — extend existing ExamResult dimensions**:
```python
CAPABILITY_TAXONOMY = {
    "code_generation": ["correctness", "style", "efficiency", "test_coverage"],
    "code_review": ["bug_detection", "security", "completeness", "false_positive_rate"],
    "research": ["coverage", "accuracy", "source_quality", "synthesis"],
    "conversation": ["goal_alignment", "tone", "conciseness", "pushback_quality"],
    "tool_use": ["selection", "arguments", "efficiency", "error_recovery"],
    "planning": ["decomposition", "dependency_tracking", "verification", "adaptability"],
}

@dataclass
class CapabilityReport:
    capability: str
    dimensions: dict[str, float]     # dimension → score
    overall: float                    # weighted aggregate
    trend: str                        # improving/stable/declining
    weakest_dimension: str            # where to focus improvement
    sample_failures: list[str]        # example failures for diagnosis
```

**Integration with self_eval.py**: The existing `ExamResult.dimensions` already supports per-dimension scoring. Extend with the taxonomy above and add trend tracking across exam runs.

---

## 5. Architecture Recommendations for Orchestrator

### 5.1 Immediate (Low effort, high value)

| Pattern | File to modify | What to do |
|---------|---------------|------------|
| Rubric-based scoring | `eval_loop.py` | Add `RubricScore` alongside existing `EvalIssue` |
| Bootstrap CIs | `self_eval.py` | Add confidence intervals to `ExamResult` reporting |
| Trajectory capture | Governor | Log tool calls + reasoning as `TrajectoryStep` list |
| Resource limits | `eval_loop.py` | Add token/time budgets to `LoopState` |

### 5.2 Medium term (Moderate effort)

| Pattern | What to build |
|---------|--------------|
| LLM-as-judge | Dedicated judge prompt template + separate model call in Governor quality review |
| Task-adaptive rubrics | AdaRubric-style rubric generation from task descriptions |
| Regression detection | Bootstrap-based regression alerts when fitness scores drop |
| Eval dashboard tab | New section in dashboard showing score trends + per-capability breakdown |

### 5.3 Future (When needed)

| Pattern | Trigger |
|---------|---------|
| Multi-judge consensus | When single-judge eval shows high variance or bias |
| MicroVM sandboxes | When executing untrusted external code |
| Dynamic task generation | When static Clawvard exams get saturated |
| Self-consistency checks | Before promoting patterns to boot.md |
| Contamination detection | If using external benchmarks for evaluation |

---

## 6. Key Repos to Watch

| Repo | What | Stars | Why care |
|------|------|-------|---------|
| [safety-research/bloom](https://github.com/safety-research/bloom) | Anthropic's behavioral eval generator | ~2k | Auto-generates diverse eval scenarios |
| [langchain-ai/agentevals](https://github.com/langchain-ai/agentevals) | Trajectory eval from OTel traces | ~1k | Framework-agnostic, works with any agent |
| [microsoft/ai-agent-evals](https://github.com/microsoft/ai-agent-evals) | GitHub Action for agent eval | ~500 | CI/CD integration with confidence intervals |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | pytest-compatible LLM testing | ~5k | Best DX for local eval |
| [langchain-ai/openevals](https://github.com/langchain-ai/openevals) | Pre-built evaluators | ~1k | Ready-made scoring functions |
| [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | K8s sandbox CRD | ~800 | Future sandboxing standard |
| [taubenfeld/CISC](https://github.com/taubenfeld/CISC) | Confidence-weighted self-consistency | ~200 | 40% sample reduction |
| [bassrehab/spark-llm-eval](https://github.com/bassrehab/spark-llm-eval) | Distributed eval with stats | ~100 | Bootstrap CIs + significance testing |

---

## 7. Pattern Count

| Category | Patterns |
|----------|---------|
| Scoring | 6 (LLM-as-judge, multi-evaluator, rubric, trajectory, tool-use, self-consistency) |
| Sandboxing | 5 (Docker, MicroVM, filesystem, network, resource limits) |
| Dataset | 4 (versioning, contamination, dynamic generation, difficulty calibration) |
| Reporting | 4 (dashboards, regression, confidence intervals, per-capability) |
| **Total** | **19 patterns** |

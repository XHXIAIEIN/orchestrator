# Claude Code Deep Dive: Teleport / Ultraplan / Ultrareview / Feature Flags

**Date**: 2026-04-01
**Source**: Kuberwastaken/claude-code (leaked npm sourcemap mirror)
**Priority**: P0 — 6 architectural patterns directly applicable to orchestrator

---

## 1. Teleport: Session Migration Architecture

### What's in a "Teleport Bundle"

Teleport serializes a full session for cross-machine migration. Two distinct flows:

**Resume flow (remote → local):**
```
teleportResumeCodeSession(sessionId)
  → fetchSession(sessionId)           // GET /v1/sessions/{id}
  → validateSessionRepository()       // compare local git remote vs session's git source
  → teleportFromSessionsAPI()         // GET session logs (try v2 GetTeleportEvents, fallback to session-ingress)
  → filter(isTranscriptMessage && !isSidechain)  // strip sidechain messages
  → checkOutTeleportedSessionBranch() // git checkout the branch CCR created
  → processMessagesForTeleportResume() // deserialize + inject resume notice
```

A "teleport bundle" contains:
1. **Session messages** — full conversation transcript, deserialized from remote threadstore
2. **Branch name** — the `claude/*` branch CCR created (extracted from session outcomes)
3. **Resume notice** — synthetic user message: `"This session is being continued from another machine. Application state may have changed. The updated working directory is ${cwd}"`

**Repo mismatch handling** (`validateSessionRepository`):
- Compares `owner/repo` AND host (strips ports for GHES compat: `ghe.corp.com:8443` matches `ghe.corp.com`)
- Four states: `match` | `mismatch` | `not_in_repo` | `no_repo_required`
- On mismatch: throws `TeleportOperationError` with formatted chalk error, includes both session and current repo for display
- On `not_in_repo`: error message includes host for GHES users

**Branch checkout** — three-tier fallback:
```
1. git checkout {branch}              // local branch exists
2. git checkout -b {branch} --track origin/{branch}  // create tracking branch
3. git checkout --track origin/{branch}               // last resort
→ ensureUpstreamIsSet() after success
```

### Create flow (local → remote)

`teleportToRemote()` — source selection ladder:

```
Source selection:
  1. GitHub clone (if CCR can pull it — checkGithubAppInstalled preflight)
  2. Git bundle fallback (if .git exists and tengu_ccr_bundle_seed_enabled gate)
  3. Empty sandbox (no .git)

Override: CCR_FORCE_BUNDLE=1 skips preflight
Override: skipBundle=true disables bundle entirely (autofix needs GitHub push)
```

**Session creation payload** (POST /v1/sessions):
```typescript
{
  title: string,
  events: [
    // Permission mode set via control_request BEFORE first user turn
    { type: 'event', data: { type: 'control_request',
      request: { subtype: 'set_permission_mode', mode, ultraplan: bool } } },
    // Initial message (if any)
    { type: 'event', data: { type: 'user', message: { role: 'user', content } } }
  ],
  session_context: {
    sources: [{ type: 'git_repository', url, revision, allow_unrestricted_git_push? }],
    seed_bundle_file_id?: string,  // alternative to GitHub clone
    outcomes: [{ type: 'git_repository', git_info: { type: 'github', repo, branches } }],
    model: string,
    reuse_outcome_branches?: boolean,
    github_pr?: { owner, repo, number },
    environment_variables?: Record<string, string>  // write-only, stripped from Get/List
  },
  environment_id: string
}
```

**Key pattern: events-before-container**
> Initial events are written to threadstore before the container connects, so the CLI applies the mode before the first user turn — no readiness race.

### Git Bundle: Progressive Size Reduction

`createAndUploadGitBundle()` — three-tier fallback chain:

```
1. git bundle create --all              // full repo + refs/seed/stash (WIP)
   → if > 100MB (tunable via tengu_ccr_bundle_max_bytes)...
2. git bundle create HEAD               // current branch only
   → if still too large...
3. squashed-root commit (git commit-tree HEAD^{tree} -m "seed")
   → single parentless commit snapshot, no history
```

WIP capture: `git stash create` → `update-ref refs/seed/stash` (makes it reachable in bundle). Untracked files intentionally excluded. Cleanup always runs in `finally` block.

**Steal pattern**: Progressive degradation chain with size constraints. Our Docker exec could use this for context shipping — full workspace → HEAD → snapshot.

---

## 2. Ultraplan: CCR Planning with Approval Flow

### Architecture

```
User types "ultraplan <prompt>"
  → keyword detection (findUltraplanTriggerPositions)
  → launchUltraplan()
    → setAppState({ ultraplanLaunching: true })  // prevent duplicate launches
    → launchDetached()  // fire-and-forget
      → checkRemoteAgentEligibility()
      → teleportToRemote({ permissionMode: 'plan', ultraplan: true, model: opus46 })
      → registerRemoteAgentTask()
      → startDetachedPoll(sessionId, 30min timeout)
        → pollForApprovedExitPlanMode()  // 3s interval, up to 600 calls
```

### ExitPlanModeScanner: Stateful Event Stream Classifier

This is the most interesting pattern. A **pure stateful classifier** that ingests `SDKMessage[]` batches:

```typescript
class ExitPlanModeScanner {
  private exitPlanCalls: string[] = []          // tool_use IDs
  private results = new Map<string, ToolResultBlockParam>()
  private rejectedIds = new Set<string>()
  private terminated: { subtype: string } | null = null

  ingest(newEvents: SDKMessage[]): ScanResult
  // Returns: approved | teleport | rejected | pending | terminated | unchanged
}
```

**Precedence**: approved > terminated > rejected > pending > unchanged

**Phase state machine** (derived from event stream + session status):
```
running → (turn ends, no ExitPlanMode) → needs_input
needs_input → (user replies in browser) → running
running → (ExitPlanMode emitted, no result yet) → plan_ready
plan_ready → (rejected) → running
plan_ready → (approved) → poll resolves
```

**Two approval paths:**
1. `approved` — user clicks approve in browser. Plan extracted from `"## Approved Plan:\n"` marker in tool_result content. `executionTarget: 'remote'`
2. `teleport` — user clicks "teleport back to terminal". Plan extracted from `__ULTRAPLAN_TELEPORT_LOCAL__\n` sentinel in a **rejection** tool_result. `executionTarget: 'local'`

### Resilience patterns:
- Max 5 consecutive poll failures before abort (transient network tolerance)
- `shouldStop` callback checks task status each tick (cooperative cancellation)
- Session status idle + no new events = `needs_input` (browser waiting for user)
- `quietIdle` guard: only trust idle when no events flowing (prevents false needs_input)

### Keyword detection: Context-aware trigger

`findKeywordTriggerPositions()` — sophisticated skip logic:
- Inside paired delimiters (backticks, quotes, brackets) → skip
- Path/identifier context (`src/ultraplan/foo.ts`, `--ultraplan-mode`) → skip
- Followed by `?` → skip (it's a question about the feature)
- Starts with `/` → skip (it's a slash command)
- Apostrophe handling: `"let's ultraplan it's"` still triggers

`replaceUltraplanKeyword()`: `"please ultraplan this"` → `"please plan this"` (preserves casing)

**Steal pattern**: Smart keyword interception before the prompt reaches the model. We could use this for intent routing in the Telegram channel.

---

## 3. Ultrareview: Billing Gate + Remote Code Review

### Billing gate flow (`checkOverageGate`)

```
Team/Enterprise → proceed (included in plan)
fetchQuota + fetchUtilization in parallel
  quota.reviews_remaining > 0 → proceed (free review N of M)
  !extraUsage.is_enabled → not-enabled (nudge to billing page)
  available < $10 → low-balance
  !sessionOverageConfirmed → needs-confirm (show dialog)
  else → proceed (bills as Extra Usage)
```

**Key pattern**: `sessionOverageConfirmed` is a one-time flag per session. Once user confirms overage billing via dialog, all subsequent `/ultrareview` calls skip the dialog. Confirmation only persists after non-aborted launch (Escape during launch doesn't set the flag).

### Launch flow — two modes:

**PR mode** (`/ultrareview 123`):
- Detects GitHub repo, passes `refs/pull/N/head` as revision
- Uses synthetic `env_011111111111111111111113` environment ID
- Env vars: `BUGHUNTER_PR_NUMBER`, `BUGHUNTER_REPOSITORY`

**Branch mode** (`/ultrareview`):
- Computes merge-base SHA against default branch
- Uses git bundle (captures uncommitted changes)
- Passes merge-base SHA as `BUGHUNTER_BASE_BRANCH` (not branch name — `git remote remove origin` in container deletes refs)
- Early bail on empty diff

**Review config** (GrowthBook `tengu_review_bughunter_config`):
```
fleet_size: 5 (max 20)
max_duration_minutes: 10 (max 25)
agent_timeout_seconds: 600 (max 1800)
total_wallclock_minutes: 22 (max 27, leaves ~3min for finalization under 30min poll)
```

**Steal pattern**: The `posInt(value, fallback, max)` guard pattern — GB cache can return stale wrong-type values, so every config read has type checking + bounds clamping.

---

## 4. Feature Flag System (GrowthBook)

### Architecture: NOT compile-time elimination

Claude Code uses **GrowthBook** (runtime feature flags via remote eval), NOT compile-time flags:

```typescript
// Three access tiers:
getFeatureValue_CACHED_MAY_BE_STALE<T>(feature, default)  // sync, hot-path safe
checkGate_CACHED_OR_BLOCKING(gate)                         // async, blocks on init if needed
getFeatureValue_DEPRECATED<T>(feature, default)            // async, legacy

// Special gates:
checkSecurityRestrictionGate(gate)  // async, waits for reinit if auth changed
checkStatsigFeatureGate_CACHED_MAY_BE_STALE(gate)  // legacy naming
```

### Caching layers:

```
1. Env overrides: CLAUDE_INTERNAL_FC_OVERRIDES (ant builds only, JSON object)
2. In-memory: remoteEvalFeatureValues Map (populated from remote eval response)
3. GrowthBook SDK: client.getFeatureValue() (with targeting/experiment logic)
4. Disk cache: savedGlobalConfig (persists between sessions for faster cold start)
```

### Key patterns:

**Stale-read tolerance**: `_CACHED_MAY_BE_STALE` returns immediately from memory/disk, never blocks. Used in render loops and hot paths. GB refreshes periodically (every ~2min) and on auth change.

**Security gate escalation**: `checkSecurityRestrictionGate` waits for `reinitializingPromise` if GrowthBook is re-initializing after auth change. Prevents stale security decisions.

**Exposure dedup**: `loggedExposures` Set prevents duplicate experiment exposure events when the same feature is read repeatedly in render loops.

**Refresh signal**: `onGrowthBookRefresh()` — subscribers register once, fire on every GB refresh. Handles race: if init completes before subscriber registers, fires catch-up on next microtask.

**Build-time USER_TYPE**: `"external"` vs `"ant"` — controls dev-only features (prompt overrides, env var overrides). Not a compile-time flag system, just a build define.

**Steal pattern**: Three-tier read strategy (sync cached → async blocking → deprecated). Our orchestrator configs should follow this — fast sync reads for hot paths, blocking reads for security gates.

---

## 5. CCR Client Architecture (ccrClient.ts)

### Transport layer for Cloud Container Runtime:

```typescript
class CCRClient implements SSETransport {
  // Heartbeat: 20s interval (server TTL 60s)
  // Stream events: 100ms batching window
  // Auth: JWT with expiry check, 10 consecutive 401s before giving up
  // Event upload: SerialBatchEventUploader (batched, ordered)
  // State sync: WorkerStateUploader (worker registration + state polling)
}
```

**Text delta coalescing**: stream_event messages accumulate in a delay buffer (100ms). text_delta events for the same content block merge into a **self-contained snapshot** per flush — a client connecting mid-stream sees complete text, not fragments.

**Auth resilience**: Distinguishes expired JWT (immediate exit, retry futile) from uncertain 401 (server hiccup). 10 × 20s heartbeat ≈ 200s ride-through window.

**Steal pattern**: Self-contained snapshot coalescing for streaming. If we build real-time agent output streaming, each flush should be complete, not a diff.

---

## 6. Cross-cutting: Local → Remote Handoff

### The CCR abstraction in one flow:

```
LOCAL CLI                          CLOUD (CCR)
─────────                          ───────────
1. checkRemoteAgentEligibility()
2. Source decision (GitHub/bundle/empty)
3. teleportToRemote()
   → POST /v1/sessions
     { events, session_context }
   → receive session.id             4. Container boots, clones/unbundles
                                    5. Reads events from threadstore
                                    6. Applies permission mode
                                    7. Starts executing
4. registerRemoteAgentTask()
5. Poll loop (3s interval)           ← Events written to threadstore
   → GET /v1/sessions/{id}/events
   → cursor-based pagination (50 pages max)
6. Session metadata for status       ← GET /v1/sessions/{id}
7. archiveRemoteSession()           8. Rejects new events
   → POST /v1/sessions/{id}/archive
```

### Environment selection priority:
```
1. Explicit environmentId (e.g. CODE_REVIEW_ENV_ID for ultrareview)
2. settings.remote.defaultEnvironmentId
3. First anthropic_cloud environment (retry once if missing)
4. First non-bridge environment
5. First available
```

---

## Patterns for Orchestrator

| # | Pattern | Source | Applicability |
|---|---------|--------|---------------|
| P0-1 | **Progressive Bundle Fallback** | gitBundle.ts | Ship workspace context to Docker containers: full→HEAD→snapshot with size limits |
| P0-2 | **Stateful Event Stream Classifier** | ExitPlanModeScanner | Parse agent output streams for approval/rejection/phase transitions without I/O |
| P0-3 | **Events-Before-Container** | teleportToRemote | Write initial config (permission mode, first message) to shared store before agent container boots — eliminates readiness races |
| P0-4 | **Three-Tier Feature Read** | GrowthBook | sync_cached → async_blocking → deprecated. Hot paths never block; security gates always block |
| P0-5 | **Session Overage Confirmation** | reviewRemote.ts | One-time billing/approval flag per session — confirm once, auto-proceed after. Only persist after successful action |
| P0-6 | **Self-Contained Snapshot Coalescing** | ccrClient.ts | Stream output batching where each flush is a complete state, not a diff. Late joiners see full text |
| P1-1 | **Keyword Trigger with Context Exclusion** | keyword.ts | Smart intent detection that skips quoted strings, paths, questions |
| P1-2 | **Source Selection Ladder** | teleportToRemote | GitHub clone → bundle → empty sandbox, with preflight checks at each tier |
| P1-3 | **Cooperative Cancellation via shouldStop** | ccrSession.ts | Poll loop checks callback each tick, parent sets status=killed |
| P1-4 | **Config Read with Type Guard + Bounds Clamp** | reviewRemote.ts | `posInt(value, fallback, max)` — defensive read from potentially stale/wrong-type remote config |

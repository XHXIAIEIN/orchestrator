# Artifact Frontmatter Schema

Canonical definition of the unified YAML frontmatter schema for steal reports, plan files, and memory files. Skills read this file at start to know what fields to emit and validate.

---

## Steal Report Schema

Required fields for files in `docs/steal/`:

| Field | Type | Allowed Values | Description |
|-------|------|---------------|-------------|
| `phase` | string (fixed) | `steal` | Identifies artifact type |
| `status` | string | `in-progress` \| `complete` | Current state of the steal round |
| `round` | integer | any positive int | Steal round number (e.g., 80) |
| `source_url` | string | any URL | URL of the target repository or resource |
| `evidence` | string | `verbatim` \| `artifact` \| `impression` | Reliability tier of the steal report content |
| `verdict` | string | `adopt` \| `park` \| `kill` \| `partial` | Overall steal outcome |
| `gaps` | list | list of gap structs (may be empty `[]`) | Cross-phase gaps discovered during this steal round |

### Steal Report Example

```yaml
---
phase: steal
status: complete
round: 80
source_url: https://github.com/example/eureka
evidence: artifact
verdict: partial
gaps:
  - phase: plan
    note: "Assumption A3 (Python availability in CI) was never validated during the steal."
    severity: minor
    resolved: false
    resolved_in: null
---
```

---

## Plan File Schema

Required fields for files in `docs/plans/`:

| Field | Type | Allowed Values | Description |
|-------|------|---------------|-------------|
| `phase` | string (fixed) | `plan` | Identifies artifact type |
| `status` | string | `draft` \| `ready` \| `in-progress` \| `complete` | Current state of the plan |
| `verdict` | string | `proceed` \| `proceed-with-caution` \| `blocked` \| `done` \| `null` | Plan execution decision |
| `evidence_strength` | string | `strong` \| `medium` \| `weak` \| `null` | Confidence level of the plan's assumptions |
| `overridden` | bool | `true` \| `false` | Whether an owner gate override occurred for this plan |
| `override_reason` | string or null | any string \| `null` | Verbatim override reason if `overridden: true` |
| `gaps` | list | list of gap structs (may be empty `[]`) | Gaps registered from upstream or downstream phases |

### Plan File Example

```yaml
---
phase: plan
status: draft
verdict: proceed
evidence_strength: strong
overridden: false
override_reason: null
gaps:
  - phase: steal
    note: "R80 steal report lacks frontmatter — forward-only migration per A1."
    severity: minor
    resolved: false
    resolved_in: null
---
```

---

## Gap Struct Definition

Every entry in a `gaps` list MUST conform to this structure:

| Field | Type | Allowed Values | Description |
|-------|------|---------------|-------------|
| `phase` | string | any phase name | Which upstream/downstream phase this gap belongs to |
| `note` | string | any string | Human-readable description of the gap |
| `severity` | string | `minor` \| `significant` | Impact level of the gap |
| `resolved` | bool | `true` \| `false` | Whether the gap has been addressed |
| `resolved_in` | string or null | artifact filename \| `null` | Which artifact resolved this gap, if any |

### Cap Rule

If `gaps[]` contains **2+ entries with `severity: significant`** → treat `evidence_strength` ceiling as `medium`.
If `gaps[]` contains **3+ entries with `severity: significant`** → treat `evidence_strength` ceiling as `weak`.

Rationale: accumulated significant unknowns degrade plan confidence regardless of the base assessment.

---

## Protocol B' — Cross-Artifact Write Rule

The **only** permitted cross-artifact write is:

> Flipping `resolved: false → true` and filling `resolved_in` on an **existing** gap entry, when the owning phase is being rerun and the downstream phase has been confirmed complete.

All other cross-artifact writes (adding new fields, modifying non-gap fields) are forbidden without owner authorization.

---

## Validation Rules (for smoke-test-frontmatter.py)

A file with a YAML frontmatter block (`---` ... `---`) is conformant if:

1. `phase` field is present and is a string
2. `status` field is present
3. `gaps` field is present and is a list
4. For each gap entry in `gaps`:
   - Keys `phase`, `note`, `severity`, `resolved` are all present
   - `severity` is `"minor"` or `"significant"`
   - `resolved` is a boolean

Files without any `---` frontmatter block are **skipped** (not failed) — forward-only migration.

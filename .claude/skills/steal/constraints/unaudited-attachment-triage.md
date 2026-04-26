# Layer 0: Unaudited-Attachment Triage — No Metadata→Verdict Jumps

**Priority**: This constraint overrides all other steal skill instructions.

## Rule

When a steal target ships binary attachments (zip, tar, tgz, exe, whl, pyc, dmg, iso, or any other archive/executable) referenced by the README or linked from the project surface, the steal report MUST NOT draw security, governance, or supply-chain conclusions about those attachments without opening them.

Metadata signals — star count, repo age, author reputation, "Download" button pattern, embedded binary presence — gate **triage**, not **verdict**. They raise "this deserves a pre-flight check". They never raise "this is malicious / trojan / compromised / suspicious payload".

## Exit Gate (fires before Phase 3 report is finalized)

If the target contains unaudited binaries, pick exactly one path:

**(a) Audit the contents.** Extract the archive. List files. Inspect anything that executes or imports (`.py`, `.js`, `.sh`, `.exe`, `setup.py`, `__init__.py`, `postinstall` hooks). Write findings from actual content.

**(b) Label as unaudited.** Set the Security/Governance dimension status to `N/A (unaudited)` with `na_reason` = "binaries present but not opened during this steal". The TL;DR must explicitly say "unaudited attachments — not evidence of compromise" (or equivalent). Every downstream section that mentions the attachments must use triage language, never verdict language.

Writing a verdict ("likely trojan", "supply-chain attack", "malicious payload") without path (a) is **banned**. The archive's verdict status after path (b) is "unknown", not "malicious".

## Violation indicators

- Report calls something "malicious", "trojan", "compromised", "suspicious payload", or "likely supply-chain X" with no code-level evidence extracted from the archive
- Security/Governance status is set to "Novel (hazard)" or similar hazard label when the hazard was inferred from file metadata, not file contents
- TL;DR conflates "attachments not opened" with "attachments are dangerous"
- Gaps Identified treats unopened archives as confirmed threats instead of triage triggers

## Enforcement

Before finalizing any Security/Governance claim in a steal report, self-check:

1. Did I open the artifact?
2. If no, is my language triage-level (unaudited / unopened / unknown) or verdict-level (malicious / trojan / compromised)?
3. If verdict-level without opening — stop, rewrite to triage, or go open the artifact now.

The Post-Generation Validation step (Phase 3) checks schema completeness. This Exit Gate checks **epistemic discipline** and runs first.

## Source

R80 `prompt-engineering-models` retrospective — the original R80 draft jumped from "zero stars + zip + README download button" directly to "likely supply-chain trojan" without opening either archive. Owner flagged as a metadata→verdict failure mode. Correction committed in `4384c0d` (docs(steal): R80 retrospective). This constraint codifies the lesson so future rounds cannot repeat the jump.

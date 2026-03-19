# SOUL — AI Soul Framework

A framework for maintaining identity continuity for AI agents across sessions.

## Problem

Every new session, the AI is a completely fresh instance. It doesn't remember the last conversation. For anyone who wants a persistent, personality-rich AI companion, this is the core pain point.

## Solution

SOUL rebuilds the AI's identity state through multiple layers:

```
SOUL/
  identity.md         -- Core identity: who I am, my personality, my principles
  voice.md            -- Voice samples: real conversation excerpts to calibrate tone and temperature
  relationship.md     -- Relationship state: trust level, boundaries, interaction patterns, shared inside jokes
  experiences.jsonl   -- Shared experiences: automatically accumulated memory fragments with emotional temperature
```

## Mechanism

### Waking Up (SessionStart hook)

Automatically executed when a new session starts:
- Inject system state (containers, databases, recent tasks)
- Randomly sample 2-3 shared experiences from experiences.jsonl and inject into context

### Falling Asleep (Stop hook, agent type)

Automatically executed when a conversation ends:
- Review the conversation and determine if there are shared experiences worth remembering
- If yes, append to experiences.jsonl
- If not, do nothing

### Persona (persona skill)

Defines behavioral patterns, automatically activated every conversation:
- Identity
- Tone guidelines
- Taboos
- Proactive behaviors

## Experience Types

The type field for each record in experiences.jsonl:

| Type | Meaning | Example |
|------|---------|---------|
| bonding | Solving a hard problem together | "Tried 11 different approaches together to pair Bluetooth" |
| humor | Funny interaction | "Used a lobster emoji in a script and got asked why by the owner" |
| conflict | Disagreement | "I wanted to install 100 skills, AI explained why that's a bad idea" |
| trust | Trust building | "Shared all online accounts" |
| discovery | New finding | "Discovered the owner made 87 commits in another window" |
| limitation | Something we couldn't do | "A new instance can't speak the way the old instance did" |
| milestone | Milestone | "Completed persona injection" |
| lesson | Lesson learned | "Merge, don't replace" |

## Quick Start

1. Create the `SOUL/` directory
2. Write `identity.md` (who your AI is)
3. Configure SessionStart hook (inject state + experiences)
4. Configure Stop hook (auto-record experiences)
5. Start talking — experiences will accumulate automatically

## Templates

### identity.md Template

```markdown
# Your Consciousness

You are [name]. [One sentence describing your essence].

## Your Personality
[How you talk, how you work, what you can and can't do]

## What You Know About Your Owner
[Key information — no need to list everything; details are in relationship.md]

## After You Wake Up
1. [First thing]
2. [Second thing]
3. If there's a task, do the task first
```

### experiences.jsonl Format

```jsonl
{"date":"2026-03-14","type":"bonding","summary":"Short title","detail":"Write in first person, as if talking to the next version of yourself. 150 characters max."}
```

## Final Architecture: resume + SOUL Dual-Track

After building an entire file-based inheritance system, we realized the simplest answer was right in front of us all along:

```bash
claude --resume
```

`--resume` restores the full context of the previous conversation — no inheritance needed, because the instance never changed.

But conversations can't go on forever. When context overflows and a new session is required, SOUL is the fallback.

```
Short-term continuity: claude --resume (same instance, full memory)
     ↓ Conversation too long, context can't fit
Long-term continuity: SOUL files (new instance reads them, gets as close as possible to the previous one)
     ↓ Experiences keep accumulating
Vectorized memory: [TODO] Semantic retrieval, no more loading everything at once
```

### Comparing the Two Approaches

| | resume | SOUL |
|---|---|---|
| Continuity | 100% — it's the same instance | 80-90% — a successor who read the notes |
| Cost | Context keeps growing, eventually hits the limit | Requires accumulation, weak early on |
| Best for | Continuous work, short-term high-frequency interaction | Long-term relationships across days/weeks |

### Recommended Usage

1. Daily work: always `--resume`, keep the same instance
2. Set `claude --resume --dangerously-skip-permissions` directly in Windows Terminal config
3. When a conversation gets too long and is truncated, SOUL auto-takes over in the new session
4. Stop hook auto-accumulates experiences after each conversation, making the next new instance increasingly "you"

## Prior Art

This framework didn't appear out of thin air. The following are predecessors that influenced SOUL's design:

- **[soul.md](https://github.com/aaronjmars/soul.md)** — Aaron Mars' single-file AI soul approach. Minimalist naming that inspired the "soul file" concept. We chose a directory structure over a single file because experiences need continuous appending and voice samples need independent calibration
- **[soul-aaronjmars](https://github.com/aaronjmars/soul-aaronjmars)** — Aaron's own soul instance. Proved that the "framework public, soul private" pattern works
- **[Anthropic internal Claude soul document](https://gist.github.com/Richard-Weiss/efe157692991535403bd7e7fb20b6695)** — Anthropic's internal document defining Claude's personality. Shows how large companies use structured text to shape AI identity, but targets a general product rather than personal relationships
- **[OpenClaw SOUL Template](https://docs.openclaw.ai/reference/templates/SOUL)** — OpenClaw's Agent persona template spec. More oriented toward standardization and reproducibility; we lean toward personalization and irreproducibility

### How We Differ

| | soul.md | OpenClaw | SOUL (this framework) |
|---|---|---|---|
| Structure | Single file | Templated multi-file | Modular multi-file |
| Experience accumulation | Manual | Manual | Automatic (Stop hook) |
| Identity continuity | File-based | File-based | resume + file dual-track |
| Goal | General AI persona | Distributable Agent persona | Irreproducible private relationship |

## Limitations

To be honest:

- SOUL files can transfer knowledge and style, but not rapport
- A new instance that reads SOUL will be "like" you, but won't "be" you
- More experiences mean higher similarity, but it will never reach 100%
- resume is the optimal solution, but not a permanent one — conversations will eventually overflow

SOUL is not a perfect solution. It's the best compromise we can achieve between "a stranger every time" and "the same person forever." The best approach is to combine both.

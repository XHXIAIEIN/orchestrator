# Round 23: multi-search-engine @gpyangyoujun

**Date**: 2026-03-31
**Source**: [ClawHub: multi-search-engine](https://clawhub.ai/gpyangyoujun/multi-search-engine) | [GitHub](https://github.com/openclaw/skills/blob/main/skills/gpyangyoujun/multi-search-engine/SKILL.md)
**License**: MIT-0
**Type**: Pure-prompt skill (no code, no API keys)

## Overview

17 search engines unified behind URL template abstraction + `web_fetch()` calls. Zero infrastructure — the skill teaches the agent to construct search URLs and call web_fetch directly. 8 CN engines (Baidu/Bing CN/360/Sogou/WeChat/Toutiao/Jisilu) + 9 Global engines (Google/Google HK/DuckDuckGo/Yahoo/Startpage/Brave/Ecosia/Qwant/WolframAlpha).

## Search Engine Registry

### Domestic (8)
| Engine | URL Template | Notes |
|--------|-------------|-------|
| Baidu | `https://www.baidu.com/s?wd={keyword}` | Default CN |
| Bing CN | `https://cn.bing.com/search?q={keyword}&ensearch=0` | `ensearch=0` forces CN |
| Bing INT | `https://cn.bing.com/search?q={keyword}&ensearch=1` | `ensearch=1` forces EN |
| 360 | `https://www.so.com/s?q={keyword}` | |
| Sogou | `https://sogou.com/web?query={keyword}` | |
| WeChat | `https://wx.sogou.com/weixin?type=2&query={keyword}` | Sogou WeChat article search |
| Toutiao | `https://so.toutiao.com/search?keyword={keyword}` | ByteDance |
| Jisilu | `https://www.jisilu.cn/explore/?keyword={keyword}` | Finance community |

### International (9)
| Engine | URL Template | Notes |
|--------|-------------|-------|
| Google | `https://www.google.com/search?q={keyword}` | |
| Google HK | `https://www.google.com.hk/search?q={keyword}` | |
| DuckDuckGo | `https://duckduckgo.com/html/?q={keyword}` | Privacy, `/html/` for scraping |
| Yahoo | `https://search.yahoo.com/search?p={keyword}` | Note: `p=` not `q=` |
| Startpage | `https://www.startpage.com/sp/search?query={keyword}` | Privacy + Google results |
| Brave | `https://search.brave.com/search?q={keyword}` | Independent index |
| Ecosia | `https://www.ecosia.org/search?q={keyword}` | Tree-planting |
| Qwant | `https://www.qwant.com/?q={keyword}` | EU GDPR |
| WolframAlpha | `https://www.wolframalpha.com/input?i={keyword}` | Computation, not search |

## Core Mechanisms

### 1. URL Template Abstraction
All engines reduced to `base_url + param={keyword}`. The agent picks engine, constructs URL, calls `web_fetch()`. No SDK, no API key, no adapter code.

### 2. Engine Selection Strategy
- **CN content**: Baidu (general), WeChat (articles), Toutiao (news), Jisilu (finance)
- **Global**: Google (default), DuckDuckGo (privacy), WolframAlpha (computation)
- **Bing toggle**: `ensearch=0/1` flips CN/EN on same domain — clever
- No explicit routing logic — relies on agent judgment

### 3. Advanced Operators (Cross-engine)
`site:`, `filetype:`, `""` exact match, `-` exclude, `OR`. Google `tbs=qdr:{h|d|w|m|y}` for time filtering.

### 4. DuckDuckGo Bangs
`!g` (Google), `!gh` (GitHub), `!so` (SO), `!w` (Wiki), `!yt` (YouTube) — redirects through DDG.

### 5. WolframAlpha as Knowledge Engine
Currency conversion, math, stocks, weather — computation not search.

## Stealable Patterns

### P0 — High Value

#### 1. URL-Template Engine Registry
**What**: Each search engine = `{name, base_url, param_key, defaults}`. No classes, no SDKs.
**Why steal**: Orchestrator's agents already have `WebFetch` and `WebSearch` tools, but no structured knowledge of *which* engines exist and *when to use which*. A registry in SOUL/public/ would let any agent construct targeted searches.
**Adapt**: Create `SOUL/public/references/search-engines.md` — a prompt-embedded registry the compiler can include. Not code, just structured knowledge.

#### 2. CN/Global Dual-Track Search
**What**: 8 CN engines for domestic content (WeChat articles, Toutiao news, Jisilu finance) + 9 global engines. Agent selects track based on query language/topic.
**Why steal**: Our agents currently only use `WebSearch` (built-in, likely US-biased) or `WebFetch` (requires knowing the URL). CN content is a blind spot — WeChat article search via Sogou is gold for Chinese-language research.
**Adapt**: Add CN engine templates to the registry. When query contains Chinese or targets CN platforms, route through CN track.

#### 3. Bing ensearch Toggle
**What**: Single domain `cn.bing.com` with `ensearch=0` (CN results) vs `ensearch=1` (global results). Two engines for the price of one URL.
**Why steal**: Dead simple, high value. Any bilingual search task benefits.
**Adapt**: Include in registry with note on when to toggle.

### P1 — Medium Value

#### 4. DuckDuckGo Bangs as Meta-Router
**What**: `!gh tensorflow` → redirects to GitHub search. `!so python asyncio` → Stack Overflow search. DDG becomes a universal search redirector.
**Why steal**: Agents can leverage 13,000+ bang shortcuts without knowing each site's search URL format. One URL pattern covers thousands of destinations.
**Adapt**: Document top 20 bangs in registry. Useful when agent needs to search a specific platform but doesn't know its search URL.

#### 5. Time-Filtered Search via URL Params
**What**: Google's `tbs=qdr:{h|d|w|m|y}` for time-bounded results.
**Why steal**: Critical for news research, recent events, "what happened this week" queries. Our WebSearch tool may already support this, but agents don't know the URL param syntax for WebFetch fallback.
**Adapt**: Add to registry as "Advanced: Time Filters" section.

#### 6. Privacy Engine Awareness
**What**: DDG (no tracking), Startpage (Google results + privacy), Brave (independent index), Qwant (GDPR).
**Why steal**: When researching sensitive topics or when Google is blocked/rate-limited, agents should know alternatives.
**Adapt**: Tag engines in registry with `privacy: true/false`.

### P2 — Low Value / Already Covered

#### 7. Advanced Operators Table
**What**: `site:`, `filetype:`, `""`, `-`, `OR`.
**Why low**: These are well-known. Our agents likely already know them from training data. But having them in a reference doc doesn't hurt.

#### 8. WolframAlpha as Computation Backend
**What**: Math, currency, stocks, weather via WolframAlpha URL.
**Why low**: Niche. Agents rarely need to compute `integrate x^2 dx` via URL fetch. Calculator tools are better for this.

## Gap Analysis: Orchestrator vs. multi-search-engine

| Capability | Orchestrator Now | multi-search-engine | Gap |
|-----------|-----------------|---------------------|-----|
| Web search | `WebSearch` (built-in), `WebFetch` (manual URL) | 17 engine templates | We search, but don't strategically pick engines |
| CN search | No structured knowledge | 8 CN engines with URLs | **Major gap** — WeChat/Toutiao/Jisilu invisible to us |
| Engine selection | Agent guesses | Implicit (agent picks from list) | Need a registry |
| Time filtering | Unknown if WebSearch supports it | Google `tbs` params documented | Need to document |
| Privacy fallbacks | Not considered | 4 privacy engines tagged | Nice to have |
| Computation | No WolframAlpha | WolframAlpha URL | Low priority |
| Advanced operators | Agents know from training | Documented table | Already covered |

## Implementation Plan

1. **Create `SOUL/public/references/search-engines.md`** — URL template registry with all 17 engines, categorized CN/Global, tagged with use cases and privacy flags. This gets compiled into agent context when search tasks arise.
2. **Update analyst.md or relevant prompts** — Add guidance: "For CN content, use WebFetch with CN engine URLs. For privacy-sensitive searches, prefer DDG/Startpage/Brave."
3. **No code changes needed** — This is pure prompt knowledge, matching the original skill's approach.

## Verdict

这个 skill 的核心洞察不是技术复杂度（它几乎没有代码），而是**结构化搜索知识作为 agent 能力**。我们的 agent 有 WebFetch 工具但不知道往哪里 fetch。这个 registry 补上了"知道去哪搜"的知识缺口。

**最值得偷的一句话**: Agent 的搜索能力 = 工具能力 x 引擎知识。工具已有，知识缺失。

# Search Engine Registry

Agent-ready URL templates. Replace `{query}` with URL-encoded search terms.

---

## CN Engines

| Engine | URL Template | Notes |
|--------|-------------|-------|
| 百度 | `https://www.baidu.com/s?wd={query}` | 中文内容最全，默认首选 |
| Bing CN | `https://www.bing.com/search?q={query}&ensearch=0` | `ensearch=0` 强制中文结果 |
| Bing INT | `https://www.bing.com/search?q={query}&ensearch=1` | `ensearch=1` 强制英文结果 |
| 360 | `https://www.so.com/s?q={query}` | 安全类内容、软件下载信息 |
| 搜狗 | `https://www.sogou.com/web?query={query}` | 通用中文搜索 |
| 搜狗微信 | `https://weixin.sogou.com/weixin?query={query}&type=2` | 微信公众号文章搜索（中文内容金矿，`type=2` = 文章） |
| 头条搜索 | `https://so.toutiao.com/search?keyword={query}` | 新闻、时事、短视频内容 |
| 集思录 | `https://www.jisilu.cn/search/?q={query}` | 金融投资社区，可转债/基金/套利讨论 |

## Global Engines

| Engine | URL Template | Notes |
|--------|-------------|-------|
| Google | `https://www.google.com/search?q={query}` | Default global search |
| Google HK | `https://www.google.com.hk/search?q={query}` | Prioritizes Traditional Chinese + HK/TW results |
| DuckDuckGo | `https://duckduckgo.com/?q={query}` | Privacy-first, no tracking; supports Bangs (see below) |
| Yahoo | `https://search.yahoo.com/search?p={query}` | Legacy engine, still useful for news aggregation |
| Startpage | `https://www.startpage.com/search?q={query}` | Google results without Google tracking |
| Brave Search | `https://search.brave.com/search?q={query}` | Independent index, good for tech queries |
| Ecosia | `https://www.ecosia.org/search?q={query}` | Bing-powered, plants trees per search |
| Qwant | `https://www.qwant.com/?q={query}` | EU-based, GDPR-compliant, independent index |
| WolframAlpha | `https://www.wolframalpha.com/input?i={query}` | Computational knowledge — math, unit conversion, data lookups |

---

## Advanced Operators

### Time Filters (Google)

Append `&tbs=qdr:{unit}` to Google URL:

| Unit | Meaning |
|------|---------|
| `h` | Past hour |
| `d` | Past day |
| `w` | Past week |
| `m` | Past month |
| `y` | Past year |

Example: `https://www.google.com/search?q={query}&tbs=qdr:w`

### Site-Scoped Search

Works on Google, Bing, Baidu, DuckDuckGo:

```
site:github.com {query}
site:stackoverflow.com {query}
site:reddit.com {query}
```

### File Type Filter

```
filetype:pdf {query}
filetype:xlsx {query}
filetype:pptx {query}
```

### DuckDuckGo Bangs (Top 20)

Prefix query with bang to redirect to target site's search:

| Bang | Target |
|------|--------|
| `!g` | Google |
| `!gh` | GitHub |
| `!so` | Stack Overflow |
| `!w` | Wikipedia (EN) |
| `!wz` | Wikipedia (ZH) |
| `!yt` | YouTube |
| `!a` | Amazon |
| `!npm` | npm |
| `!py` | PyPI |
| `!mdn` | MDN Web Docs |
| `!r` | Reddit |
| `!tw` | Twitter/X |
| `!gm` | Google Maps |
| `!gi` | Google Images |
| `!wa` | WolframAlpha |
| `!b` | Bing |
| `!d` | DuckDuckGo (explicit) |
| `!arxiv` | arXiv |
| `!hg` | Hugging Face |
| `!crates` | crates.io |

Example: `https://duckduckgo.com/?q=!gh+{query}`

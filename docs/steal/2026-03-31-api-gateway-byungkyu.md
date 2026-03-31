# api-gateway @byungkyu (maton-ai)

> 来源：ClawHub — https://clawhub.ai/byungkyu/api-gateway
> GitHub：https://github.com/maton-ai/api-gateway-skill
> 日期：2026-03-31
> 下载量：59.5k | 安装量：459 | Stars：291
> 许可证：MIT-0

---

## 概述

透明代理网关，用一个 API key 调用 100+ 第三方 API，OAuth 由网关托管。不造新抽象——原生 API 路径直通，网关只做认证注入和连接路由。

## 核心架构

### 双平面分离

| 平面 | Base URL | 职责 |
|------|----------|------|
| **数据平面** (Gateway) | `gateway.maton.ai/{app}/{native-path}` | 请求代理、OAuth 注入、header/query 透传 |
| **控制平面** (Ctrl) | `ctrl.maton.ai/connections` | 连接 CRUD、OAuth 授权流、状态管理 |

这是经典的 data-plane / control-plane 分离。数据平面无状态高吞吐，控制平面管生命周期。

### 请求流

```
Client → gateway.maton.ai/{app}/... → 验证 MATON_API_KEY → 查找 app 对应的 active connection
  → 注入 OAuth token → 代理到目标 API → 原样返回（status code + body 透传）
```

### 连接模型

- **认证方式**：`OAUTH2`（主流）、`API_KEY`、`BASIC`、`OAUTH1`、`MCP`
- **连接状态**：`ACTIVE` / `PENDING` / `FAILED`
- **多账号**：同一 app 可有多个 connection，通过 `Maton-Connection: {id}` header 选择
- **默认策略**：省略 header 时用最老的 active connection

### 透传原则

- HTTP method 全支持（GET/POST/PUT/PATCH/DELETE）
- 自定义 header（除 Host/Authorization）原样转发
- Query params 原样透传
- 错误码和 body 原样返回，不包装不转换
- 限速：10 req/s/account + 目标 API 自身限制

## 支持的 130+ 服务

覆盖 8 大类：
- **Google 全家桶** (17)：Mail/Drive/Sheets/Docs/Calendar/Contacts/Forms/Tasks/Slides/Analytics/Ads/BigQuery/Merchant/Play/Search Console/Meet/Classroom
- **Microsoft 365** (6)：Teams/Excel/To Do/OneNote/OneDrive/Outlook/SharePoint
- **CRM/Sales** (8)：HubSpot/Salesforce/Pipedrive/Zoho CRM/ActiveCampaign/Keap/Attio/Twenty
- **通信** (6)：Slack/Discord/Telegram/WhatsApp Business/Twilio/Quo
- **项目管理** (10)：Notion/Airtable/Monday/Asana/ClickUp/Trello/Jira/Linear/Basecamp/Wrike
- **开发者** (7)：GitHub/Vercel/Netlify/Firebase/Supabase/Sentry/PostHog
- **支付/财务** (6)：Stripe/Square/QuickBooks/Chargebee/Xero/Zoho Books
- **营销/邮件** (10+)：Mailchimp/GetResponse/Brevo/Kit/Klaviyo/Lemlist/Instantly/SendGrid/MailerLite/Constant Contact

## 可偷模式

### P0 — 立刻能用

#### 模式 1：Transparent Gateway（透明网关模式）
**核心思想**：不发明新 API，只做认证注入 + 路由。`/{app}/{native-path}` 保留目标 API 的原生路径，客户端不需要学新接口。

**为什么值得偷**：Orchestrator 当前调外部 API（Telegram/GitHub/各种 webhook）都是在业务代码里直接写认证逻辑。如果加更多集成（QQ 音乐、微信、Notion），认证代码会爆炸。

**适配方案**：在 Orchestrator 的 channel 层之上加一个 `gateway/` 模块：
- `gateway.py`：统一的 `request(app, path, method, body, headers)` 函数
- 认证信息从 `SOUL/private/credentials/` 加载（不用 Maton 托管，自己管）
- 每个 app 一个 adapter 文件只负责 token refresh 逻辑
- 业务代码只调 `gateway.request("telegram", "/sendMessage", ...)`

#### 模式 2：Control-Plane / Data-Plane 分离
**核心思想**：连接管理（CRUD、OAuth flow、状态追踪）和数据代理完全解耦。

**为什么值得偷**：Orchestrator 的 Telegram bot token 直接写在 env 里，没有连接状态管理。加新 channel 时没有统一的"连接是否活跃"检查。

**适配方案**：
- 控制平面：`connections/` 模块管理所有外部连接的 lifecycle（create/test/refresh/revoke）
- 数据平面：现有 channel 层只负责消息收发
- 连接状态表：`connections.json` 记录每个连接的 status/last_refresh/expiry

#### 模式 3：Multi-Connection per App（多账号路由）
**核心思想**：同一个服务可以有多个认证连接，通过 header 显式选择或走默认策略。

**为什么值得偷**：Orchestrator 可能需要多个 Telegram bot（一个日常、一个审批专用）、多个 GitHub token（个人 + org）。

**适配方案**：连接配置支持 `connection_id`，调用时可指定 `connection="approval-bot"`，默认走主连接。

### P1 — 值得借鉴

#### 模式 4：OAuth-as-Infrastructure（OAuth 下沉为基础设施）
**描述**：OAuth 授权流（redirect → callback → token → refresh）从业务代码完全剥离，变成基础设施的一部分。业务代码只需要"给我一个 active token"。

**适配**：Orchestrator 目前不需要完整 OAuth 流（大部分用 API key），但如果将来接 Google/Microsoft，可以参考此模式把 OAuth 封装成 `auth_provider.py`。

#### 模式 5：Error Passthrough（错误透传不包装）
**描述**：网关不吃掉目标 API 的错误码和 body，原样返回。客户端能直接根据目标 API 的文档排查问题。

**适配**：Orchestrator 现有的错误处理经常在中间层吞掉原始错误信息。channel 层应该把上游 API 的原始 status + body 保留在 error context 里。

#### 模式 6：Instruction-Only Skill（纯指令型技能）
**描述**：整个 skill 没有一行可执行代码，只有 SKILL.md 指令。靠 prompt 驱动 agent 用 urllib/fetch 直接调 API。

**适配**：Orchestrator 的 skill 体系可以借鉴——不是所有能力都需要写代码。有些 integration 只需要一份"怎么调"的文档 + 认证信息就够了。

### P2 — 了解即可

#### 模式 7：App-Name Prefix Routing
URL 路径第一段即为路由 key（`/slack/...`、`/google-mail/...`）。简单粗暴但够用。

#### 模式 8：Default Connection Strategy
多连接场景下"最老的 active connection 作为默认"——简单的 fallback 策略，避免配置爆炸。

## OAuth 实现分析

**Token 管理策略**：
- 用户通过 Maton 的 OAuth UI 完成授权，网关拿到 access_token + refresh_token
- 每次 gateway 请求时，网关检查 token 有效性，过期则自动 refresh
- 用户只持有 MATON_API_KEY（一级密钥），不直接接触各 API 的 OAuth token（二级密钥）
- **双层密钥模型**：一级密钥认证身份，二级密钥认证服务——一级密钥泄露不导致三方服务泄露（需要显式 OAuth 授权）

**Orchestrator 可借鉴点**：
- 即使不用 Maton 托管，也可以实现类似的双层密钥：`ORCHESTRATOR_MASTER_KEY` → 查找对应 app 的 token → 注入
- Token refresh 逻辑应该在 gateway 层自动完成，业务代码无感知

## API 抽象层设计评价

**设计哲学**：**不抽象**。这是最有意思的地方——api-gateway 的设计选择是**零抽象**。

- 没有统一的 `createContact()`、`sendMessage()` 等高级 API
- 没有跨平台的数据模型转换
- 只做最薄的一层：认证注入 + 路由

**优点**：
- 支持的 API 数量可以爆炸式增长（加新服务只需要加 OAuth adapter，不需要设计抽象接口）
- 不存在"抽象泄露"问题——用户本来就在写原生 API 调用
- 维护成本极低

**缺点**：
- 用户必须熟悉每个目标 API 的文档
- 无法实现"换一个 CRM 但代码不改"的可替换性

**对 Orchestrator 的启示**：
Channel 层已经有 Telegram/微信的适配器，这些适配器是有价值的（统一了消息模型）。但对于**工具型集成**（查 GitHub issue、读 Notion 页面、发邮件），走透明代理比写高级抽象更实际。两种模式可以共存：
- **Channel 层**：有统一抽象（Message/Event 模型）
- **Tool 层**：走透明代理（原生 API 直通）

---

## 总结

api-gateway 的核心价值不在技术复杂度（其实很简单），而在**设计选择的克制**：不造新抽象、不包装错误、不管业务逻辑，只做认证注入这一件事。130+ API 支持的规模恰好验证了这种克制的正确性——如果每个 API 都要设计统一接口，根本做不到这个量级。

对 Orchestrator 来说，P0 模式 1-3（透明网关 + 双平面 + 多账号）值得在下一次扩展 channel/tool 集成时落地。

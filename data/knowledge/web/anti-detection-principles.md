# 反检测原则

从 GoLogin / browser-use / web-access 偷师总结的防检测知识。
不是要做反检测浏览器，而是让采集器不被误封。

## 核心原则

### 1. 一致性比隐藏更重要
- 不要隐藏指纹（反而可疑），要让指纹"看起来正常"
- 如果用代理：UA、timezone、geolocation 必须跟代理 IP 地理位置一致
- 如果 UA 说 Windows，不要暴露 macOS 的 Canvas 指纹

### 2. 行为模式是最终检测手段
- 指纹可以伪造，行为模式很难伪造
- 自动化特征：操作间隔恒定、无鼠标移动轨迹、瞬间填表
- 对策：关键操作间加随机延迟（200-800ms），用 browser_click_at 替代 JS click

### 3. Session 持久化减少登录频率
- 每次重新登录本身就是可疑行为
- 保持 cookie/localStorage 持久化，减少认证次数
- 按平台隔离 profile，避免跨站 cookie 泄露

## 平台特性（待积累）

按需填充，格式：
```yaml
domain: example.com
detection: [cloudflare, datadome]  # 使用的检测系统
requires: [cookie-persist, random-delay]  # 需要的对策
notes: "..."
```

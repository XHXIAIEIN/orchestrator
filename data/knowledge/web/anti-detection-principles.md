# 反检测原则

从 GoLogin / browser-use / web-access 偷师总结的防检测知识。

## 已落地

### 1. Session 持久化减少登录频率
- 保持 cookie/localStorage 持久化，减少认证次数
- 按平台隔离 profile（BrowserRuntime.profile_dir），避免跨站 cookie 泄露

## 待落地

### 2. 一致性比隐藏更重要
- 让指纹"看起来正常"，比隐藏指纹更有效
- 代理场景：UA、timezone、geolocation 与代理 IP 地理位置保持一致
- 跨信号一致性：UA 说 Windows 就别暴露 macOS 的 Canvas 指纹

### 3. 行为模式拟人化
- 指纹可以伪造，行为模式是最终检测手段
- 自动化特征：操作间隔恒定、无鼠标移动轨迹、瞬间填表
- 方案：关键操作间加随机延迟（200-800ms），用 browser_click_at 替代 JS click

### 4. 引擎级指纹控制
- Canvas/WebGL 受控噪声算法（同 profile 一致，跨 profile 不同）
- 适用条件：需要多账号运营时
- 来源：GoLogin Orbita 引擎

## 平台特性（待积累）

按需填充，格式：
```yaml
domain: example.com
detection: [cloudflare, datadome]  # 使用的检测系统
requires: [cookie-persist, random-delay]  # 需要的对策
notes: "..."
```

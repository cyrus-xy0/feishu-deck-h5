# 共享后端持久化（可选）

默认 `build.py` 生成的 deck 把改动存到浏览器 `localStorage`（仅本机本浏览器），
导出 HTML 时把顺序/隐藏 bake 进 `window.__INIT`。这对单机够用，但有两个硬限制：

1. **发布到妙笔 html-box 后存不住**：妙笔把 deck 套在 `sandbox` 的 iframe 里，且
   **没有 `allow-same-origin`** → 内部 origin 为 opaque → 浏览器**禁用 localStorage /
   sessionStorage / BroadcastChannel**。点「保存」会静默失败，刷新即丢。
2. **无法共享**：localStorage 是本机的，发链接给别人，对方看不到你的改动。

挂上 `--faas` 后，deck 改用一个 FaaS 存储后端，实现「**改了即存、关了再开还在、
发链接给别人对方看到最新版、还能继续改同一份**」。

## 为什么必须经过 FaaS 中转（不能浏览器直连存储）

- 妙笔的 `/api/tos/sign`（取 TOS 预签名 PUT 地址）**带 CORS**（`ACAO` 回显 origin），
  浏览器可调。
- 但 **TOS 对象本身（`magic-builder.tos-…volces.com`）的 PUT/GET 不返回 CORS 头**，
  所以浏览器 `fetch` 直接读写 TOS 会被跨域拦截（`<img>` 能加载、`fetch` 不行）。
- 于是用一个 **FaaS 做中转**：
  - 浏览器 ↔ FaaS：由 FaaS 自己回 `ACAO:*`；POST 用 `text/plain` 成为「简单请求」
    免预检（OPTIONS）。
  - FaaS ↔ TOS：服务端调用，无跨域问题。FaaS GET 时服务端抓 TOS 公链返回；POST 时
    服务端 `sign` + `PUT` 写回 TOS。

```
浏览器(沙箱iframe, 无localStorage)
   │  GET/POST  (CORS:*, text/plain 免预检)
   ▼
FaaS  /api/faas/<id>   ──服务端──►  /api/tos/sign + PUT/GET  ──►  TOS 对象(每deck一个)
```

## 部署与接线

1. **部署存储函数**：`scripts/faas_store.js`，用 `publish-magic-faas` skill（或直接
   `POST /api/faas`）。拿到 `record_id`，调用地址 = `https://magic.solutionsuite.cn/api/faas/<id>`。
   - 函数内 `KEY = "deck-store/<context.id>.json"`：每个函数实例对应一个 TOS 对象，
     天然按 deck 隔离。多个 deck 各发一个函数即可，互不串。
2. **生成 HTML 带上后端**：
   ```bash
   python3 scripts/build.py manifest.json --out index.html \
     --faas "https://magic.solutionsuite.cn/api/faas/<id>"
   # 或在 make_manifest 阶段 --faas，把地址烤进 manifest
   ```

## 前端行为（带 --faas 时）

- 加载：`fetch(FAAS)` 拉取 `{edits, order, hidden}` 并应用（共享同一份）。
- 编辑：输入时 **debounce 自动保存**（1.5s）防丢；💾 保存 = 立即写回。
- 调序/隐藏：改动后立即写回后端。
- 数据模型（存进 TOS 的 JSON）：
  ```json
  { "edits": { "<slideIdx>.<boxIdx>": "<innerHTML>" },
    "order": [视觉顺序的页索引...],
    "hidden": { "<pageIdx>": true } }
  ```
- 共享语义：**单文档、后写覆盖**（last-write-wins）。适合「一个人维护、多人查看 /
  偶尔协作」的销售 deck 场景；不是实时多人协同（要实时需上 WebSocket/CRDT）。

## 不带 --faas

完全退回原行为：localStorage 存改动 + 导出 HTML（`window.__INIT` bake 顺序/隐藏）。
适合纯本机 / 静态托管、不需要跨设备共享的场景。

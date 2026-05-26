# Shared Asset Library

`assets/shared/` 是 H5 deck 的公共素材库。它服务两个入口:

- 本地 agent 生成 deck 时按名字、类型、行业检索素材。
- 飞书 bot 生成 remote zip / 在线预览时保留可追踪素材引用。

## 当前集合

| 目录 | 类型 | 用途 |
|---|---|---|
| `clientlogo/` | logo | 客户、PE/VC、品牌标识 |
| `feishu-products/` | icon/logo | 飞书产品官方标识 |
| `third-party-logos/` | icon/logo | 第三方产品标识 |
| `bytedance-products/` | icon/logo | 字节系产品标识 |
| `digital_employee_avatars_50/` | avatar/image | 通用数字员工头像 |
| `mydigitalemployee/` | avatar/image | 内部命名 persona |

未来可新增:

| 目录 | 类型 | 用途 |
|---|---|---|
| `images/<industry>/` | image | 行业场景、产品、空间、设备 |
| `videos/<industry>/` | video | 客户现场、产品演示、动效素材 |
| `icons/<style>/` | icon | 非商标图标集 |
| `demos/<scenario>/` | demo | 可嵌入的 HTML demo 或 prototype |

## 索引

运行:

```bash
python3 skills/feishu-deck-h5/assets/catalog-assets.py
```

会生成:

```
skills/feishu-deck-h5/assets/shared/asset-index.generated.json
```

CI / 本地检查:

```bash
python3 skills/feishu-deck-h5/assets/catalog-assets.py --check
```

索引 schema 在 `asset-index.schema.json`。索引是机器读取的 ground truth,
不要手改生成文件。

## 命名规则

- 客户 logo 保留用户常用中文名,必要时另建 alias 字段,不要复制多份文件。
- 飞书产品标识必须使用官方文件,不要让模型手画商标。
- 视频和 demo 文件名使用 kebab-case,例如 `store-task-agent-demo.html`。
- 新增客户现场图时,文件名不要暗示未确认事实,例如不要写
  `customer-success-30-percent-growth.png`。

## 使用优先级

1. 用户提供的真实素材。
2. 本库已收录且来源清楚的素材。
3. H5 中用 HTML/CSS 重建的示意 UI。
4. 明确标注为“示意”的生成图。

找不到 logo / icon / demo 时,在 outline 的 `asset_plan` 暴露缺口,不要
临时画商标或伪造客户现场。

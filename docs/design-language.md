# 设计语言(DocumentCheck Design Language)

> 目标:**商务大气、不"AI 味"、不喧宾夺主**。
> 以 Ant Design v5 为底座,通过 ConfigProvider + 少量自定义 token 收拢风格。
>
> 代码入口:`frontend/src/theme/tokens.ts` / `antdTheme.ts` / `AppThemeProvider.tsx`

---

## 1. 总原则(必须遵守)

| # | 原则 | 反例 |
|---|---|---|
| 1 | 主色克制,不用高饱和紫 / 渐变粉 / 霓虹 | Vercel 紫粉渐变、ChatGPT 紫、AI Sparkle |
| 2 | 不用玻璃拟态(backdrop-filter: blur)、不用发光 | Apple Liquid Glass、Neumorphism |
| 3 | 表格/表单的信息密度优先,不追求大留白 | SaaS landing style "呼吸感" |
| 4 | 语气色偏砖质,不用霓虹红/荧光绿 | `#ff0044`、`#00ff88` |
| 5 | 动画克制,duration ≤ 250ms,无弹性/爆破 | framer-motion spring、parallax |
| 6 | 字体用系统栈,不引外链 Google Font | `Inter`、`Space Grotesk` |
| 7 | 图标用 @ant-design/icons 线性款,不用拟人/卡通 | 3D 渲染 emoji、AI 头像 |

---

## 2. 色彩 Token

| Token | 值 | 用途 |
|---|---|---|
| `primary` | `#1d4584` | 品牌主色、主按钮、Link 强调 |
| `primaryHover` | `#163868` | 主按钮 hover |
| `primaryBg` | `#eef3fb` | 主色弱背景(Tag、Badge、Alert Info) |
| `textPrimary` | `#1f2328` | 正文 |
| `textSecondary` | `#5c6370` | 次要说明 |
| `textTertiary` | `#8a919d` | 时间、辅助信息 |
| `border` | `#e4e7ed` | 常规边框 |
| `bgBase` | `#ffffff` | 卡片、表单 |
| `bgLayout` | `#f5f7fa` | 页面底色 |
| `danger` | `#c53030` | 错误、删除按钮 |
| `success` | `#2d7a4a` | 成功、低风险 |
| `warning` | `#c27c0e` | 警告、中风险 |

**不要新增高饱和色**。需要强调时用 `primary` 的明暗变化,不加新色系。

---

## 3. 字体 & 字号

```
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
             "PingFang SC", "Microsoft YaHei", sans-serif;
```

| 场景 | 字号 | 字重 |
|---|---|---|
| 页面一级标题 | 22px | 600 |
| 页面二级标题 / 卡片标题 | 18px | 600 |
| 正文 | 14px | 400 |
| 次要说明 | 12-13px | 400 |
| 表格表头 | 14px | 500 |

**行高 1.6**,标题 `1.35`。不做斜体,不做大字号营销文案。

---

## 4. 间距 & 尺寸

间距规则:**4 的倍数**。常用:4 / 8 / 12 / 16 / 24 / 32 / 48。

- 卡片内边距:16~24
- 表单项间距:20~24
- 控件高度:36(中)/ 28(小)/ 44(大)
- 圆角:**6px**(基础)/ 8px(大卡片)/ 4px(Tag、Badge)

---

## 5. 阴影

只有两档可用,且都轻:

- `boxShadow`:`0 1px 2px rgba(17,24,39,0.04), 0 1px 3px rgba(17,24,39,0.06)`
- `boxShadowSecondary`(浮层):`0 2px 4px rgba(17,24,39,0.04), 0 4px 8px rgba(17,24,39,0.06)`

**不用**:彩色阴影、内阴影、多层叠加、发光。

---

## 6. 布局

### 6.1 认证页(登录 / 改密)
左栏品牌深蓝渐变(`#1d4584` → `#142f5d`)+ 右栏白色表单(max-width 400)。
窄屏(≤ 900px)收敛为单栏。

### 6.2 应用主壳(项目列表、管理后台等)
- 顶栏 `56px` 粘性,白底 + 底部 1px 边框
- 左侧品牌 mark(28px 圆角方块,渐变底色)+ 系统名
- 右侧用户头像下拉(修改密码 / 登出 / 管理入口)
- 内容区 `max-width: 1440px`,水平居中,内边距 24

---

## 7. 组件使用规范

### 按钮
- 主要动作:`<Button type="primary">`,每屏**最多 1~2 个**主按钮
- 次要:`<Button>`(default)
- 破坏性:`<Button danger>`,绝不用 primary 色表达"删除"
- 禁用 `ghost` + 玻璃效果

### 表格
- 头 `#fafbfc` 浅灰,行 hover `#f7f9fc`
- 紧凑模式(`size="small"`)用于多列表格
- 分页靠右,默认 pageSize 12 或 20

### 标签(Tag)
- 状态类用 antd 内置颜色(processing / success / warning / error / default)
- 不自定义彩色 Tag

### 反馈
- 错误:`<Alert type="error" showIcon>`
- 成功:顶部 `message.success`(2s 自动消失)
- 危险确认:`modal.confirm({ okButtonProps: { danger: true } })`

---

## 8. 文案规范

- 中文半角标点:**冒号**、**逗号**、**括号**全部使用半角,不用"，。、"
- 按钮动词一致:**新建 / 查看 / 删除 / 保存 / 取消 / 确认 / 提交**
- 错误文案不用"Oops / 哎呀",直接说明原因与下一步
- 列表空态用一句陈述 + CTA,不写长篇引导

---

## 9. 改造落地顺序

见 `docs/execution-plan.md` 里后续 UI 相关 change。推荐顺序:

1. ✅ 认证流(Login / ChangePassword)
2. ✅ ProjectListPage
3. ProjectCreatePage + ProjectDetailPage(上传向导最容易出"AI 味",优先验)
4. AdminUsersPage + AdminRulesPage
5. ReportPage + DimensionDetailPage
6. 4× ComparePage(文本对比是最重的,留最后)

每页改完需 L1 全绿 + 浏览器人工过一遍登录→使用→登出完整流。

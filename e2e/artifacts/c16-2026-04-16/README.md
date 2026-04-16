# C16 compare-view L3 手工凭证

> Docker kernel-lock 未解(延续 C3~C15 共因),L3 延续手工降级。

## 手工步骤(待 Docker 可用后执行)

1. 启动全栈 → 建项目 → 上传 2+ 投标人压缩包 → 跑检测
2. 进入报告页 → 对比总览 Tab → 截图 pair 列表 + Tab 栏 + 文本对比入口链接
3. 点击 text_similarity pair "文本对比" → 截图左右双栏 + 高亮段落 + 角色切换
4. 切到"报价对比" Tab → 截图矩阵表格 + 标红 + toggle 过滤
5. 切到"元数据对比" Tab → 截图矩阵表格 + 着色 + 通用值标灰

## L1 + L2 覆盖证明

- **L1 后端**: 15 用例(text 5 + price 5 + meta 5)
- **L2 后端**: 3 Scenario(text + price + metadata 全链路)
- **L1 前端**: 11 用例(TextComparePage 4 + PriceComparePage 4 + MetaComparePage 3)
- **合计**: 29 新增用例

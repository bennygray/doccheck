# C13 detect-agents-global L3 手工凭证

> **状态**:L3 Playwright 自动化延续 Docker kernel-lock 阻塞(C5~C12 继承 follow-up),暂用手工截图 + L1/L2 全绿证明替代。
> **日期**:2026-04-15

## L1 / L2 覆盖证明

- **L1**:131 新用例(error 60 + image 29 + style 42)全绿
  - `pytest backend/tests/unit/test_error_consistency_*.py` → 60 passed
  - `pytest backend/tests/unit/test_image_reuse_*.py` → 29 passed
  - `pytest backend/tests/unit/test_style_*.py` → 42 passed
  - 全量 L1 670 passed
- **L2**:8 新用例(error 4 + image 2 + style 2)全绿
  - `pytest backend/tests/e2e/test_detect_error_consistency_agent.py` → 4 passed
  - `pytest backend/tests/e2e/test_detect_image_reuse_agent.py` → 2 passed
  - `pytest backend/tests/e2e/test_detect_style_agent.py` → 2 passed
  - 全量 L2 212 passed

## L3 待补 6 张截图(Docker kernel-lock 解除后)

1. **启动检测**:项目详情页点"启动检测",SSE 显示 11 Agent 并行跑
2. **error_consistency 铁证 evidence 展开**:报告页维度明细 → 展开 `error_consistency`,看到 pair_results 含 `is_iron_evidence=true` + L-5 判断结果;红色"铁证"徽章
3. **error_consistency downgrade 展开**:identity_info 缺失场景 → evidence 标 `downgrade_mode=true`,无铁证徽章
4. **image_reuse MD5+pHash evidence 展开**:报告页展开 `image_reuse` → 看到 `md5_matches` + `phash_matches` 两组列表,byte_match 和 visual_similar 区分
5. **style 三 bidder consistent_groups 展开**:展开 `style` → 看到 L-8 输出的 `consistent_groups[]` + `limitation_note` "风格一致可能源于同一代写服务"
6. **任一 LLM 失败兜底 banner**:模拟 L-5 / L-8 LLM 失败 → 维度页显示 "AI 研判暂不可用" / "语言风格分析不可用" banner

## 复测步骤(Docker 可用后)

```bash
# 1. 启动全栈
docker compose up -d

# 2. 前端
cd frontend && npm run dev

# 3. seed 测试数据(含 identity_info 齐全 + 技术方案文档 + 图片)
cd e2e && npx tsx seed.ts --fixture=c13

# 4. 跑 Playwright(L3 最终化)
npm run e2e -- --grep "detect-agents-global"
```

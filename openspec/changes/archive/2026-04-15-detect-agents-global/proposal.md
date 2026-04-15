## Why

C6 detect-framework 注册了 11 Agent 骨架,C7~C12 已替换 8 个真实 run(),仍剩 3 个 global 型 Agent(`error_consistency / style / image_reuse`)走 dummy。本期 C13 一次性替换这 3 个,M3 进度推进至 8/9,只剩 C14 LLM 综合研判收官。

`error_consistency` 是 spec **铁证级**维度(权重 20,与硬件指纹并列 top),且有专属 LLM prompt(L-5);`style` 在 spec §F-DA-06 明确标注 `[LLM 独有维度]`,L-8 两阶段 prompt 不可被纯程序替代;`image_reuse` 是中等权重维度,数据层 `document_images.md5 + phash` 已由 C5 持久化就绪。本期一次性兑现 spec §F-DA-02 / §F-DA-03 / §F-DA-06 + §L-5 / §L-8 全部规格,避免铁证能力推后到 C14 让其 scope 失控。

## What Changes

- 替换 `agents/error_consistency.py::run()`:程序层 identity_info 关键词跨 bidder 交叉搜索 + L-5 LLM 深度判断"交叉污染"(铁证直判);两层 fallback(preflight downgrade 用 bidder.name 关键词 + L-5 LLM 失败仅展示程序 evidence 不铁证)
- 替换 `agents/image_reuse.py::run()`:MD5 精确双路 + pHash Hamming distance 双路;字节级匹配 `hit_strength=1.0`,视觉相似 `hit_strength=1-d/64`;不引 L-7 非通用图 LLM(spec "可升铁证"非"必升",占位字段保留)
- 替换 `agents/style.py::run()`:L-8 两阶段全 LLM(Stage1 每 bidder 提风格特征 + Stage2 全局比对);TF-IDF 先过滤高频通用段落再抽样;>20 bidder 切组(简化版每组 ≤20 不跨组比);任一阶段 LLM 失败 → 整 Agent skip 哨兵
- 新增子包 `error_impl/`(7 文件) + `image_impl/`(5 文件) + `style_impl/`(6 文件);3 子包并存不强行共用 — 因 3 Agent 数据源/算法耦合弱
- 扩 `_preflight_helpers.bidder_has_identity_info` 1 个新 helper(Q2 downgrade 精化)
- 扩 `tests/fixtures/llm_mock.py` 新增 L-5 + L-8 两阶段 fixture(单一入口贴 CLAUDE.md 8 调用点共享原则)
- 3 Agent 独立 env 命名空间:`ERROR_CONSISTENCY_*` / `IMAGE_REUSE_*` / `STYLE_*`(关键参数严格校验,次要参数 warn fallback)
- evidence 三 Agent 字段格式统一(`enabled / llm_explanation` 占位 + 各自语义字段);`is_iron_evidence` 标记由 `error_consistency` L-5 `direct_evidence=true` 触发(C6 契约预留字段已支持)
- spec sync:MODIFIED "11 Agent 骨架"(dummy 列表清空,加 "C13 替换完毕" Scenario)+ ADDED 8 类 Req(算法 / 降级 / mock fixture / evidence 结构 / env)
- `docs/execution-plan.md §6` 追加 2 行变更记录(不改 §3 原表):C13 改名 `detect-agents-global`(原 §3 `bidder-relation` 与实际 Agent 不符);C14 改名 `detect-llm-judge`(原 §3 `history-cooccur` 同上)

**不动**:`registry / engine / judge / context` 全锁定(11 Agent 注册表 C12 已稳定);`DIMENSION_WEIGHTS` 本期不调(占位权重留 C14 LLM 综合研判时统一调);`document_images / document_texts / bidder.identity_info` 数据层全就绪零迁移

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `detect-framework`: 3 global Agent dummy 替换为真实 run()(算法 / LLM 调用 / 降级 / evidence 结构);`_preflight_helpers` 扩 1 helper;`llm_mock.py` 扩 L-5 + L-8 两阶段 fixture;dummy 列表清空 Scenario

## Impact

- **后端代码**:`backend/app/services/detect/agents/{error_consistency,image_reuse,style}.py` 重写 run();新增 `error_impl/ image_impl/ style_impl/` 共 18 文件;`agents/_preflight_helpers.py` +1 helper;`tests/fixtures/llm_mock.py` 扩 L-5/L-8 fixture
- **前端代码**:零改动(evidence 字段为前端无感知扩展;3 Agent 名字 / 注册表条目 / DIMENSION_WEIGHTS 不变)
- **数据层**:零改动(`document_images.md5/phash` C5 已存;`bidder.identity_info` C5 已 LLM 填充;`document_texts.header_footer` C5 已分离存储)
- **依赖**:零新增(`imagehash>=4.3` 已在 pyproject.toml,C5 image_parser 已用)
- **LLM 调用点**:detect 层从 0 → 2(L-5 + L-8);生产环境每项目典型 5 家 → L-5 ~10 次 + L-8 ~6 次,与 C7 text_similarity LLM 调用同量级
- **测试**:L1 ~50 + L2 ~6~8;L3 延续手工凭证(Docker kernel-lock 解除后跑)
- **算法 version**:`error_consistency_v1 / image_reuse_v1 / style_v1`
- **风险覆盖**:RISK-19(关键词碰撞致 token 爆炸:短词过滤 len≥2 + TF-IDF 高频降权 + 候选段落 ≤100)+ RISK-20(L-1 失败致铁证静默跳过:downgrade 仍调 L-5)
- **计划文档**:`docs/execution-plan.md §6` 追加 2 行;`backend/README.md` 新增 "C13 detect-agents-global 依赖" 段

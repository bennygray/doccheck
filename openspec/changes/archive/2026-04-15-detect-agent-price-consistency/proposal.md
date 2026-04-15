## Why

M3 里程碑第 6/9 个 change。C6 已建 detect-framework 注册 10 Agent 骨架(dummy `run()`);C7/C8/C9/C10 已替换 `text_similarity` / `section_similarity` / `structure_similarity` / `metadata_{author,time,machine}` 共 6 个 Agent 的 dummy,剩 4 Agent 待落真实算法。C11 替换 **`price_consistency` Agent** 的 dummy `run()`,覆盖围标检测"报价一致性"证据链。

C11 设计基于 **"围标的物理本质 = 多家独立法人在报价行为上表现出非独立性"** 的第一性原理推导,对应真信号谱系中的"水平关系"(bidder 之间);"垂直关系"(单家 vs 群体均值/标底)归 C12 `price_anomaly`。

## What Changes

### 检测层(C11 主体,不动框架)
- 新增子包 `backend/app/services/detect/agents/price_impl/`(11 文件):
  - `__init__.py`(含 `write_pair_comparison_row` 共享 helper,复用 C10 模式)
  - `config.py`(env 读取 + 4 子检测 flag + 阈值)
  - `models.py`(evidence schema TypedDict)
  - `normalizer.py`(item_name NFKC+casefold+strip;Decimal 拆解尾 N 位 + 整数位长)
  - `extractor.py`(从 `PriceItem` 表批量 query → `{bidder_id: {sheet_name: [PriceRow]}}`)
  - `tail_detector.py`(子检测 1:尾数组合 key 跨投标人碰撞)
  - `amount_pattern_detector.py`(子检测 2:(item_name_norm, unit_price) 对精确匹配率)
  - `item_list_detector.py`(子检测 3:两阶段对齐 + 整体相似度)
  - `series_relation_detector.py`(子检测 4:等差/等比/比例关系,**基于第一性原理审暴露的漏洞新增,execution-plan §3 C11 原文未列**)
  - `scorer.py`(4 子检测合成 Agent 级 score,disabled 不参与归一化)
- 重写 `backend/app/services/detect/agents/price_consistency.py` 的 `run()`(Agent 注册元组 `name + agent_type + preflight` 不变;preflight 复用既有 `bidder_has_priced`)

### 4 子检测算法(纯程序化 + 轻量归一化,零 LLM)
- **tail(尾数)**:跨投标人 `total_price` 的 `(整数部分[-3:], len(整数部分))` 组合 key 碰撞;组合 key 区分 100/1100/8100(尾 3 位都是 100 但整数位长 3/4/4)
- **amount_pattern(金额模式)**:跨投标人 `(item_name 归一化, unit_price)` 对精确匹配率;匹配对数 / min(A 条数, B 条数) ≥ 阈值 → 命中
- **item_list(报价表项整体相似度)**:两阶段对齐
  1. 若两 bidder sheet_name 集合相同 + 每个同名 sheet 的 PriceItem 数量相同 → 判定"用同模板",按 `(sheet_name, row_index)` 位置对齐
  2. 否则 → 按 item_name NFKC 归一精确匹配;配对数 / min(A 条数, B 条数) ≥ 95% → 命中
- **series_relation(数列关系,新增子检测)**:对齐行序列的 `B/A` 比值方差 < ε → 等比命中(B = A × k);`B - A` 差值变异系数 < ε → 等差命中;要求最低对齐样本 ≥ 3 行

### 口径归一(Q2 决策:整体简化)
- C11 **不读** `price_parsing_rule.currency` 和 `price_parsing_rule.tax_included` 两个字段
- 两 bidder 报价规则口径不同时,仍按原始 `total_price / unit_price` 直接比较
- 真实"含税/币种混用导致同价不同数值"的场景留 C14 LLM 综合研判处理;业主侧报价规则配置(C4 `price-config`)负责前置统一口径

### 兜底(execution-plan §3 C11 原文对齐)
- 行级:异常样本(`total_price` 非数值 / NULL / Decimal 转换失败)→ 该行 skip,不假阳
- 子检测级:对齐样本 < 最低阈值(series 要求 ≥ 3 对齐行)→ 该子检测 skip
- 子检测级:flag 禁用 → `evidence.enabled=false`,不执行该子检测
- Agent 级:两 bidder 都无 PriceItem → preflight skip("未找到报价表");单侧无 → preflight skip
- Agent 级:4 子检测全 skip → `score=0.0` + `participating_subdims=[]` 哨兵(对齐 C9/C10)

### 配置(env,统一 `PRICE_CONSISTENCY_` 前缀)
- `PRICE_CONSISTENCY_TAIL_ENABLED` / `PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED` / `PRICE_CONSISTENCY_ITEM_LIST_ENABLED` / `PRICE_CONSISTENCY_SERIES_ENABLED`(4 子检测独立开关,默认 true)
- `PRICE_CONSISTENCY_TAIL_N`(尾数位数,默认 3)
- `PRICE_CONSISTENCY_AMOUNT_PATTERN_THRESHOLD`(默认 0.5)
- `PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD`(默认 0.95)
- `PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX`(等比方差上限,默认 0.001)
- `PRICE_CONSISTENCY_SERIES_DIFF_CV_MAX`(等差变异系数上限,默认 0.01)
- `PRICE_CONSISTENCY_SERIES_MIN_PAIRS`(最低对齐样本,默认 3)
- `PRICE_CONSISTENCY_SUBDIM_WEIGHTS`(4 子检测权重,默认 `0.25,0.25,0.3,0.2`)
- `PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER`(保护阈值,默认 5000)

## Capabilities

### New Capabilities
<!-- 无新 capability -->

### Modified Capabilities

- `detect-framework`:`price_consistency` 从 dummy 列表移除;新增约 12 Req(extractor / 4 子维度算法契约 / 两阶段对齐 / preflight / scorer 合成规则 / flag 配置 / 行级兜底 / Agent 级 skip 哨兵)

## Impact

### 受影响代码
- `backend/app/services/detect/agents/price_consistency.py`(dummy → 真实算法)
- 新增 `backend/app/services/detect/agents/price_impl/` 子包(11 文件)
- `backend/README.md`(新增 "C11 依赖" 段,9 env + 4 子检测说明)
- `.gitignore`(加 `c11-*` L3 artifacts 白名单)
- `e2e/artifacts/c11-2026-04-15/README.md`(L3 手工凭证占位)

### 受影响数据库
- 无 schema 变更(PriceItem 表 C5 已就绪,C11 只读不写)

### 受影响 spec
- `openspec/specs/detect-framework/spec.md`(约 +12 Req)

### 受影响路线图
- `docs/execution-plan.md` §6 追加一行 scope 变更记录:C11 基于第一性原理审新增 series 子检测,§3 C11 原文保留不改

### 不受影响
- `detect/registry.py` / `engine.py` / `judge.py` / `context.py`(锁定不变)
- 10 Agent 注册元组(`name + agent_type + preflight`)不变
- `AgentRunResult` 契约不变
- `price_parsing_rules` 表数据契约(C11 不读 currency/tax_included 字段)
- `DocumentSheet` 表(C11 不消费,归 C9 专管)
- C10 `metadata_impl/` 子包(零 touch)
- 前端组件不变(judge 层聚合 evidence,前端按 C6 既有渲染)

### 依赖/包
- 零新增第三方依赖(NFKC 用 `unicodedata` 标准库;方差计算用标准库 `statistics`)

### 部署
- 无需 alembic 迁移、无需回填脚本(纯算法层 change)
- 生产部署 env 覆盖建议:9 个 `PRICE_CONSISTENCY_*` env 保持默认,实战数据反馈后调阈值

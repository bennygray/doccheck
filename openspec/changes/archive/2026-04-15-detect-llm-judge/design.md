## Context

M3 里程碑(检测可执行)共 9 个 change,C14 `detect-llm-judge` 是最后一个。截至 C13 归档,11 个 Agent 已全部替换为真实算法,dummy 列表清空;`judge.compute_report` 已支持 global 型 Agent 铁证升级(读 `OverallAnalysis.evidence_json["has_iron_evidence"]`);`AnalysisReport.llm_conclusion` 字段占位为空字符串。

本 change 的职责**收敛为单一维度**:把 judge 层从"纯公式 + 铁证升级"升级为"公式 + L-9 LLM 综合研判 + 可升不可降 clamp + 失败模板兜底"。不动 11 Agent 注册表、不动 8 个 Agent 子包、不动 AgentRunResult 3 字段契约、不动数据层(无 alembic 迁移)。

**Stakeholders**:
- 后端 detect 层(judge 模块升级)
- 测试(llm_mock.py 扩 L-9 builder)
- 产品 UX(降级态前缀哨兵识别,前端轻改可在后续 UI change 补)
- requirements §L-9 对接人(综合研判自然语言结论)

**Constraints**:
- M3 收官纪律:scope 收敛,不塞"跨项目历史共现"(Q4 决策,独立 follow-up);不调 `DIMENSION_WEIGHTS`(留实战反馈)
- 投标争议场景:评分可解释性是产品根基,LLM 不能稀释铁证硬规则
- LLM 必失败:重试 + JSON 容错 + 模板兜底必须齐全,对用户无感
- 沿用 C13 LLM mock 单一入口模式,不重造

## Goals / Non-Goals

**Goals:**
- 兑现 requirements §L-9 LLM 综合研判能力,`llm_conclusion` 从空占位切到真实填充
- LLM 作为"增强"而非"权威":可升分(识别跨维度共振),不可降分(守护铁证硬规则)
- 失败兜底对用户无感:LLM 失败时报告仍出,`llm_conclusion` 降级为公式结论模板 + 前缀标语
- token 成本可预测:预聚合摘要 3~8k token,大小项目都能跑
- 不破坏 C6~C13 既有契约和测试:`compute_report` 纯函数保留作为"基础分"单一事实源

**Non-Goals:**
- 不做跨项目历史共现 LLM 上下文(Q4 决策,独立 follow-up change;需要配 bidder identity 去重)
- 不调 `DIMENSION_WEIGHTS`(留实战数据反馈,follow-up)
- 不做 L-9 prompt 的 N-shot examples 精调(首版简版,假阳/漏判反馈后精调)
- 不加 `AnalysisReport.llm_status` 字段(前缀哨兵足够,避免 alembic 迁移)
- 不抽 L-5/L-8/L-9 三处 `retry+parse` 模式到共享 helper(C13 既有 100+ 用例 mock 局部 helper,共享抽取成本高于收益;M4 第 4 次出现再抽)
- 不改前端类型(`llm_conclusion` 仍是 `string`;前端若要展示降级 banner,通过前缀 match 实现)

## Decisions

### D1 LLM 输入粒度:预聚合结构化摘要(不喂 raw evidence_json)
- **决策**:judge 侧先跑纯函数 `summarize(pcs, oas, per_dim_max, ironclad_info) -> dict`,产 11 维度结构化摘要:
  ```
  {
    "project": {"id": ..., "name": ..., "bidder_count": ...},
    "formula": {"total": ..., "level": ..., "has_ironclad": bool},
    "dimensions": {
      "<dim>": {
        "max_score": float | None,
        "ironclad_count": int,      # pair 型走 is_ironclad;global 型走 evidence.has_iron_evidence
        "participating_bidders": [...],
        "top_k_examples": [         # top-k 按 score 倒序;global 型填 single OA 摘要
          {"bidder_a": str, "bidder_b": str, "score": float, "evidence_brief": str}
        ],
        "skip_reason": str | None   # enabled=false / 数据缺失 / preflight 失败
      }
    }
  }
  ```
- **理由**(对比选项 A 全量 raw):全量 evidence_json 对 5~10 bidder 项目可达 5~15 万 token,LLM 注意力稀释且成本爆炸;L-9 的本质是"把 11 维度结论人话化",摘要足够
- **备选**:
  - A 全量 evidence_json 直喂 — token 爆炸,拒绝
  - C 分层两跳(LLM 先看摘要再回读细节)— 过度设计,LLM 调度+两跳 prompt 复杂度高,拒绝
  - D 每维度独立 LLM 调用 — 12 次调用成本×12 且丢"跨维度共振"核心卖点,拒绝
- **Q1 敲定**:B(预聚合摘要)

### D2 LLM 失败兜底:保留公式路径 + 降级模板
- **决策**:LLM 重试 N 次(`LLM_JUDGE_MAX_RETRY` default 2)全失败 / JSON 解析失败 / suggested_total 超界 → 统一走降级分支:`total=formula_total` / `level=formula_level` / `llm_conclusion=fallback_conclusion(...)` 模板
- **理由**:memory `feedback_fallback_principle` 硬约束"兜底对用户无感";公式路径 `compute_report` 已就绪,零新增代价;LLM 是增强不是必要
- **备选**:
  - B LLM 失败 skip 报告 — 5% LLM 失败率=5% 检测白跑,违背 M3 判据,拒绝
  - C 删公式路径完全靠 LLM — 单点故障,铁证硬规则被 LLM 自由裁量稀释,拒绝
- **Q2 敲定**:A

### D3 LLM clamp 规则:可升不可降,铁证硬下限守护
- **决策**:LLM 成功产出 `suggested_total` 后,按如下顺序 clamp:
  1. `final = max(formula_total, llm_suggested_total)` — 只升不降
  2. `if has_ironclad: final = max(final, 85.0)` — 铁证硬下限守护
  3. `final = min(final, 100.0)` — 天花板
  4. `level = compute_level(final)` — ≥70 high / 40-69 medium / <40 low,可能因升分跨档
- **理由**:
  - 第一性原理审:L-9 独有价值是"跨维度共振识别"(单维未过线但多维共振→实际高风险),这只需要升分方向
  - 铁证硬下限守护:防 LLM 压铁证分(95→70)这类不可控风险,投标争议场景防守力保留
  - `compute_report` 纯函数契约不变,C6~C13 累计 test 全绿
- **备选**:
  - A LLM 仅补文本不动分 — 浪费 LLM 跨维度串讲价值,拒绝
  - C LLM 可升可降 — 铁证硬规则被稀释,稳定性差,投诉场景难防守,拒绝
- **Q3 敲定**:B

### D4 跨项目历史库:不做,独立 follow-up
- **决策**:judge LLM prompt 仅含本项目 11 维度摘要,不查其他 project 的 bidders / pair_comparisons 表;"跨项目历史共现"作为独立 follow-up change 登记
- **理由**:
  - scope 纯粹,M3 收官不塞新功能
  - bidder identity 去重是独立硬课题(同公司不同 alias、壳公司、联系人交叉),简单 name 匹配信号价值低且有假阳/假阴
  - 原 execution-plan §3 C14 = `history_cooccur` 本就是独立 change 体量,C14 改名不等于可以顺便塞进来
- **备选**:
  - B 轻量 SQL cooccur 作为 LLM 上下文 — identity 去重坑 + scope 溢出,拒绝
- **Q4 敲定**:C(A 实施 + 显式 follow-up 登记)

### D5 降级态 llm_conclusion:标语前缀 + 公式结论自然语言化模板
- **决策**:LLM 失败时 `llm_conclusion` 由 `fallback_conclusion(total, level, per_dim_max, ironclad_dims) -> str` 拼模板,形如:
  > `AI 综合研判暂不可用,以下为规则公式结论:本项目加权总分 72.5 分,风险等级 high。铁证维度:error_consistency、metadata_author(共 2 项)。维度最高分:text_similarity 88、price_consistency 75、error_consistency 92。建议关注:[前 3 高分维度]。`
- **理由**:
  - 用户在降级态仍看到完整结论,对用户无感(feedback_fallback_principle)
  - 固定前缀 `"AI 综合研判暂不可用"` → 前端前缀 match 加降级 banner,无需加 DB 字段
  - 纯函数可测试(L1 覆盖)
- **备选**:
  - A 空字符串 — UX 空白差,拒绝
  - B 单行标语 — 浪费公式已算出的结论信息,拒绝
  - D 新增 `llm_status` 字段 — alembic 迁移+scope 溢出+过度设计,拒绝
- **Q5 敲定**:C

### D6 模块划分:单文件 `judge_llm.py`
- **决策**:新增 `backend/app/services/detect/judge_llm.py` 单文件,3 个纯函数(`summarize` / `call_llm_judge` / `fallback_conclusion`)平铺,不拆子包
- **理由**:
  - 对比 C13 `style_impl/` 6 文件拆子包是因有 Stage1/Stage2 双阶段+采样+LLM 客户端多职责;L-9 只有"摘要→调 LLM→兜底"单线流程,单文件足够(过度设计审通过)
  - judge.py 内部 import judge_llm,不对外暴露(`__all__` 不导出)

### D7 env 命名空间 `LLM_JUDGE_*`(5 个)
- **决策**:env 5 个,贴 C11/C12/C13 分命名空间风格:
  - `LLM_JUDGE_ENABLED` bool(default `true`)— 整 L-9 开关;false 时 `judge_and_create_report` 跳过 LLM 调用直接走降级模板分支
  - `LLM_JUDGE_TIMEOUT_S` int(default `30`)— 单次 LLM 调用超时
  - `LLM_JUDGE_MAX_RETRY` int(default `2`)— 失败重试(0=不重试,2=最多 3 次调用)
  - `LLM_JUDGE_SUMMARY_TOP_K` int(default `3`)— 每维度 top_k_examples 截断数
  - `LLM_JUDGE_MODEL` str(default 读项目既有 LLM 客户端配置,空字符串=使用 client 默认)
- **校验**:loader 函数 `load_llm_judge_config() -> LLMJudgeConfig` + 校验非法值 fallback default + warn log(贴 C11/C12 宽松风格)

### D8 LLM 输出 Schema 与解析容错
- **决策**:LLM 必须返回 JSON:
  ```
  {
    "suggested_total": float,  // 必填,0~100
    "conclusion": string,       // 必填,非空字符串,用户可读的综合研判结论
    "reasoning": string         // 可选,LLM 升分时的理由;失败兜底不读此字段
  }
  ```
- **失败判据**(统一走降级分支,不部分接受):
  - JSON 解析失败 → 降级
  - 缺必填字段(`suggested_total` / `conclusion`)→ 降级
  - `suggested_total` 超界([0, 100])→ 降级
  - `conclusion` 为空字符串 → 降级
- **理由**:部分接受会导致状态爆炸,不如统一走降级(模板+公式值),简单且可预测

### D9 clamp 顺序的边界案例处理
- **决策**:clamp 规则 D3 的 1→2→3 顺序严格,举例:
  - case1:formula=65(medium)+ LLM=75 + 无铁证 → final=75 high
  - case2:formula=88(high+铁证)+ LLM=60 → step1 max(88,60)=88;step2 铁证 max(88,85)=88;step3 min(88,100)=88(守护成功)
  - case3:formula=50(medium)+ LLM=105(超界)→ 视为失败走降级,final=50 medium
  - case4:formula=30(low)+ 无铁证 + LLM=45 → final=45 medium(跨档)
  - case5:`LLM_JUDGE_ENABLED=false` → 不调 LLM,final=formula,`llm_conclusion=fallback_conclusion(...)`(降级文案)
- **理由**:边界清晰,L1 逐条覆盖

### D10 algorithm version 与可观测性
- **决策**:`AnalysisReport` 不新增 version 字段,但在 log + `llm_conclusion`(若成功时)不硬编码版本号;在 `backend/README.md` 登记 algorithm version `llm_judge_v1`,便于实战反馈时知道是哪版 prompt
- **理由**:不污染 DB 字段,可观测性通过 log 和文档补齐即可

### D11 既有测试影响与改动
- **影响**:
  - `test_detect_judge.py` — 新加的 `judge_and_create_report` LLM 调用分支需 mock patch;既有 `compute_report` 纯函数 test 无需改(契约不变)
  - C6 `test_judge_stream.py`(若存在)— 同上,需 mock patch LLM 旁路
- **策略**:所有既有 judge test 默认 patch `call_llm_judge` 返回 `None`(等价 LLM 失败),走降级分支(total/level 保持公式值,与原测试断言一致);新的 LLM 行为独立 L1 test 覆盖

## Risks / Trade-offs

- **[Risk] LLM prompt 首版假阳/漏判**
  → Mitigation:登记 follow-up "L-9 prompt 调优",实战反馈后 N-shot examples + 输出格式约束收紧
- **[Risk] LLM 试图输出极低 suggested_total(异常 bias)影响用户观感**
  → Mitigation:`max(formula, llm)` clamp 已守护,LLM 降分完全无效;用户看到的下限就是公式值
- **[Risk] 摘要 top_k=3 可能错过"第 4 名强信号 pair"**
  → Mitigation:`LLM_JUDGE_SUMMARY_TOP_K` env 可调;铁证 pair 无论排名都单独列出(`ironclad_count` + 铁证 bidder 对明文)
- **[Risk] LLM 返回超长 `conclusion` 文本撑破前端**
  → Mitigation:LLM prompt 约束字数(~200 字);真超长也仅是 UX 问题,不 block 流程;前端可加 CSS 截断或 "Read more"(不强耦合本 change)
- **[Risk] 降级模板前缀哨兵与正常 LLM 输出冲突**
  → Mitigation:LLM prompt 明确要求"不要以'AI 综合研判暂不可用'开头";LLM 偶尔违反时,前端降级 banner 会误显示,是小 UX 问题,可接受;严格可加独立字段(D 选项),但 scope 溢出被拒
- **[Trade-off] 不抽 L-5/L-8/L-9 共享 retry+parse helper**
  → 现状:3 处相似模式,C14 写同形态内部函数;Mitigation:follow-up 登记,M4 第 4 次出现再抽,避免波及 C13 的 100+ 用例 mock
- **[Trade-off] `DIMENSION_WEIGHTS` 不调**
  → 现状:C6 占位权重沿用至今;Mitigation:follow-up 登记,实战数据反馈后调参;本期聚焦 LLM 接入,不混入权重优化
- **[Trade-off] 不做跨项目历史共现**
  → 现状:Q4 决策;Mitigation:独立 follow-up change,需先解决 bidder identity 去重(可能配合 C17 admin)

## Migration Plan

**部署步骤**:
1. 本 change apply 完毕 + L1/L2 全绿 + L3 手工凭证齐 → archive
2. 生产部署前必须设置 env:`LLM_JUDGE_ENABLED=true` + `LLM_JUDGE_MODEL` 贴现网 LLM 客户端 + 其他 3 个 env 按 default 即可
3. 若 LLM 服务未就绪,可 `LLM_JUDGE_ENABLED=false` 跑降级态(用户看到"AI 综合研判暂不可用"+公式结论模板);事后打开 enabled 即可

**回滚策略**:
- 代码回滚:`git revert` 本次 commit,judge.py 回到 C13 状态(只有 compute_report 纯函数),零数据库迁移,回滚干净
- env 回滚:`LLM_JUDGE_ENABLED=false` 等效于"不调 LLM 的降级态",无需改代码

**数据层**:无 alembic 迁移,无数据修正脚本,无回填需求;`AnalysisReport.llm_conclusion` 字段类型不变

## Open Questions

- **None**:Q1~Q5 全部敲定,design 无遗留 open question。若 apply 期发现边界案例(如 LLM 客户端接口与 C13 不一致、prompt 字数真超),就地决策并记入 handoff apply 现场决策段(沿用 C9~C13 风格)

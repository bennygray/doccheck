## Context

### 当前 judge 与 report 层的"信号稀薄"路径

`backend/app/services/detect/judge.py::judge_and_create_report` 是检测流水线的终点:
- 汇总所有 `AgentTask` 行 → 算维度分数 + 聚合 `total_score` + 依阈值档位(≥50 high / 30≤x<50 medium / <30 low)得 `risk_level`
- 调 `call_llm_judge` 用 LLM 生成 `llm_conclusion` 文本;LLM 失败时用 `fallback_conclusion` 规则文案
- 写 `AnalysisReport` 行入库

**现状漏洞**:无论 agent 数据质量如何(所有 agent 全零/全 skipped/正常),公式都会按固定阈值硬推出 `risk_level`。当 11 个 agent 里 8 个 skipped、3 个 succeeded 但分数全 0 时,final_total=0 → `risk_level=low`,LLM 拿到这些零分 summary 输出"经 X 维度比对,均未发现异常...风险极低,无围标迹象",**与事实不符**(实际是没信号,不是低风险)。A/B 案例 `fix-mac-packed-zip-parsing` 修之前就是这个状态。

### identity_info 缺失的"沉默降级"

`detect-framework` spec 明确:`error_consistency` agent preflight 检查 `bidder_has_identity_info(b)`,任一方返 False → `ctx.downgrade = True`,agent 退化为"只看文档内容字符串重合,不看身份字段"。这个降级是内部行为,UI/报告**未告知用户**"这一维度的判定是在身份信息缺失情况下做出的"。

### ROLE_KEYWORDS 三处副本分化

历史实现导致三个地方各维护一份角色关键词表,内容不完全一致(提取自 `fix-mac-packed-zip-parsing` 实施期间的 grep 结果):

| 位置 | 用途 | 特点 |
|---|---|---|
| `services/parser/llm/role_keywords.py` | runtime 兜底匹配 | 本次要改的主副本;缺"价格标/资信标"等 |
| `services/parser/llm/prompts.py:17-24` | LLM 系统 prompt 的角色描述(告诉 LLM 每个 role 是什么) | 说明性文本,LLM 看这个做分类依据 |
| `services/admin/rules_defaults.py:64-70` | admin UI 可配置关键词的默认值 | **缺 `authorization` 整条**(其他 8 个 role 都有,授权委托没有);`pricing` 关键词拼写略不同("报价/清单/工程量/商务标/投标报价" vs runtime 的"投标报价/报价清单/工程量清单/报价/清单/商务标") |

### 前端既有 pattern(从 `fix-mac-packed-zip-parsing` Explore 子 agent 扫描结果)

- **风险等级 Tag**:`ProjectListPage.tsx::RISK_COLORS`(antd Tag color literal),`ReportPage.tsx::RISK_META`(自定义 bg/color)两个字典风格共存
- **Alert 提示**:既用 antd `Alert type="warning"` 也用自定义 inline `<div style={{bg:#fcf3e3 border:#f0e0b0}}>`(`needs_password` 场景)
- **Collapse 折叠**:`DimensionDetailPage:242-302` 有 `antd Collapse ghost` 已实践
- 无 i18n 框架,中文文案 hardcode

## Goals / Non-Goals

**Goals:**
- 所有"看似完成但其实 agent 全零"的场景,用户看到的风险等级是**第三档** `indeterminate` 并附"证据不足,无法判定"原因,不是"低风险无围标"的误导
- `identity_info` 缺失时用户在 3 处(bidder 详情/报告维度/Word 导出)显式看到"身份信息缺失导致此维度已降级"
- ROLE_KEYWORDS 三处副本本次同步更新;**不**引入 single source of truth(技术债留给后续 change 专门处理,避免本次 scope 膨胀)
- `/analysis/status` 客户端能区分"agent 终态但 judge 未就绪" vs "完全完成"
- `.zip/.7z/.rar` 归档行在 UI 上不和真文档混在一起,但可展开看到"已过滤 N 个"审计文本

**Non-Goals:**
- **不**改 agent 层(ProcessPool 隔离/LLM provider 超时统一在 `harden-async-infra`)
- **不**做 identity_info 的正则内容抽取兜底(原 spec 明确不做,避免脏数据污染)
- **不**改 DB migration — `risk_level` 当前 `String(16)` 无 CheckConstraint,新增 `indeterminate` 值无需 DDL
- **不**合并 ROLE_KEYWORDS 三处副本成一个 single source of truth(技术债 follow-up)
- **不**做归档行"点击下载原包"按钮(只看 + 折叠)
- **不**定前端 `report_ready=false` 时的轮询间隔策略(留给前端实现自由)
- **不**改 `error_consistency` agent 本身的 preflight 或 run 逻辑(只在报告/UI 层展示降级状态)
- **不**做 i18n,新文案直接中文 hardcode(跟项目现状一致)

## Decisions

### D1:证据不足判定 = "非 skipped 的**信号型** agent 全部 score=0" + "无铁证"短路
判定式(伪代码):
```python
# 白名单:这些 agent 的 score=0 表示"真的没信号",算进判定分母
SIGNAL_AGENTS = {
    "text_similarity", "section_similarity", "structure_similarity",
    "image_reuse", "style", "error_consistency",
}
# 黑名单外:metadata_author / metadata_time / metadata_machine / price_consistency
# 这些 agent 的 score=0 表示"查了,没发现碰撞/异常",不代表"无信号" → 不进分母

def _has_sufficient_evidence(agent_tasks, pair_comparisons, overall_analyses) -> bool:
    # 短路 1:任一 PC.is_ironclad 或 OA.has_iron_evidence → 铁证已经构成信号
    if any(pc.is_ironclad for pc in pair_comparisons):
        return True
    if any((oa.evidence_json or {}).get("has_iron_evidence") for oa in overall_analyses):
        return True
    # 核心判定:只看信号型 agent
    signals = [t for t in agent_tasks
               if t.status == "succeeded" and t.agent_name in SIGNAL_AGENTS]
    if not signals:
        return False          # 没有任何信号型 agent 成功 → 证据不足
    return any((t.score or 0) > 0 for t in signals)  # 至少一个非零 → 有信号
```

**为什么加白名单?** 独立 reviewer 指出原判定有已知副作用 —— 真实"干净项目"里 `metadata_*` / `price_consistency` 这类 agent 的 score=0 表达的是"查了没发现碰撞",而不是"没算出来";把它们计入判定会让干净项目被误标 indeterminate。白名单把判定从"agent 跑没跑出非零" 收紧为"**信号型** agent 跑没跑出非零",语义更精准。代价:2 行常量 + 2 行过滤 + L1 多 2 个 case。

**为什么加铁证短路?** `compute_report` 的铁证升级会把 formula_total 拉到 ≥85(见 `Requirement: 综合研判骨架与评分公式` 步骤 2c)。若 hardware fingerprint 类 agent 的 AgentTask.score=0 但 PC.is_ironclad=True(agent 实现里得分规则可能没把铁证算进 score 字段),原判定会产出 total_score=85 + risk_level=indeterminate 的自相矛盾行。铁证短路保证这种场景走原 LLM 路径,结论与 formula 一致。

**为什么不用阈值(如有效信号 <30%)?** 阈值常数在"2 个非零 / 6 个"和"3 个非零 / 6 个"之间画不出业务意义的线;"全零 vs 有信号"是二分的硬性判定。

**副作用(已基本缓解):** 极少数情况下 SIGNAL_AGENTS 里的 agent 全部 skipped(如项目只有 1 个 bidder 无 pair 维度 + style agent 降级),会触发 indeterminate。这种场景本就应该被标证据不足 — 接受。

### D2:`risk_level` 枚举扩展不改 DB schema
`analysis_reports.risk_level` 当前是 `String(16)` 无 CheckConstraint(见 Alembic 0005_detect_framework.py:208),原生支持任意字符串,新增 `indeterminate` 无需 `ALTER TYPE` 也无需 Alembic migration。仅在 Pydantic Literal 和前端 Union 加 `"indeterminate"` 即可。

**为什么不加 DB CheckConstraint 锁定枚举?** 保持现状 — 后续若要严格化留给独立 change。本次只加值不限制。

### D3:`indeterminate` 配色中性灰,不共用 low 的绿/medium 的橙
- Tag 前景:`#8a919d`(与 tokens.ts `textTertiary` 同色) 
- Tag 背景:`#f5f7fa`(与 tokens.ts `bgLayout` 同色) 
- 文案:`"证据不足"` 而不是"待确认"或"无法判定"(都比"证据不足"更软,而产品语义上这就是"证据不足")

**为什么不用橙色警告?** 橙色在项目里已经是 medium 风险 + warning 提示共用,语义冲突;中性灰与 needs_password 的灰色提示条也一致。

### D4:`identity_info_status` 放 ORM 层的 `@property`,两个 schema 通过 `from_attributes=True` 读取

**第一版错误:** 在 `BidderSummary` 加 `@computed_field` 会触发 `AttributeError` — BidderSummary 当前只有 `id/name/parse_status/file_count`,没有 `identity_info` 字段可读。

**本次采用**:把 `identity_info_status` 作为 `@property` 定义在 SQLAlchemy **ORM 模型** `Bidder`(`backend/app/models/bidder.py`)上:

```python
class Bidder(Base):
    # ... 现有字段含 identity_info ...

    @property
    def identity_info_status(self) -> str:
        return "sufficient" if self.identity_info else "insufficient"
```

然后 `BidderSummary` 和 `BidderResponse` 都声明为普通字段 + `model_config = ConfigDict(from_attributes=True)` 让 Pydantic 自动从 ORM 实例读:

```python
class BidderSummary(BaseModel):
    id: int
    name: str
    parse_status: str
    file_count: int
    identity_info_status: Literal["sufficient", "insufficient"]  # 从 ORM @property 读
    model_config = ConfigDict(from_attributes=True)
```

**为什么不同时在两个 schema 写 `@computed_field`?** computed_field 需要 self.identity_info,BidderSummary 当前没这个字段;要么给 BidderSummary 也加 `identity_info: dict | None`(payload 变胖) 要么 computed_field 换写法。ORM `@property` 是 SSOT,两边 schema 零重复逻辑,零 payload 膨胀。

**为什么不用 SQLAlchemy `@hybrid_property`?** 当前不需要 SQL 过滤(仅读展示),plain `@property` 更简单;需要 SQL 过滤时一行改 `@hybrid_property` 升级成本忽略。

**为什么不让 Drawer 打开时单独拉 `/bidders/{id}` 换 BidderResponse?** 多一个请求,不如就在 BidderSummary 里加字段。

### D5:前端 `indeterminate` 的覆盖靠"类型收紧"而不是"人工 grep"
独立 reviewer 指出原设计里"TypeScript 编译强制覆盖"是**虚假保证** —— 项目当前代码多处用了宽类型和运行期兜底,扩 union 不会报错:
- `types/index.ts:25,199`:`Project.risk_level: ProjectRiskLevel | string | null` 有 `| string` 逃生门
- `ProjectListPage.tsx:61,67`:`RISK_COLORS/LABELS` 是 `Record<string, string>` 不是 `Record<RiskLevel, ...>`,缺 case 不报错
- `ReportPage.tsx:211`:`report.risk_level as RiskLevel ?? RISK_META.low` 硬 cast + 运行期兜底会静默 fallback 到 low

本 change MUST 同时做**类型收紧**让漏改真的会编译/运行失败,否则 `indeterminate` 会被悄悄吞掉:
1. `types/index.ts`:`RiskLevel`、`ProjectRiskLevel` union 加 `"indeterminate"`;**删除 `| string` 逃生门**(改为 `| null`)
2. `ProjectListPage.tsx::RISK_COLORS` / `RISK_LABELS`:类型从 `Record<string, string>` 收紧为 `Record<RiskLevel, string>`,漏 case 编译 fail
3. `ReportPage.tsx::RISK_META`:已是 `Record<RiskLevel, ...>`,加 `indeterminate` 后编译即通;**删除 L211 的 `as RiskLevel` cast 和 `?? RISK_META.low` 运行期兜底**,改为直接索引 `RISK_META[report.risk_level]`(类型系统保证非 null)
4. `ReportPage.tsx` 内 `GaugeCard`:跟随 RISK_META 自动生效
5. `components/reports/ReviewPanel.tsx::STATUS_OPTIONS`(L24-29):只有当复核面板也按 risk_level 筛选时才需要改;本次只保证渲染 tag,不改筛选语义
6. Word 模板:`templates.py` 内按 `risk_level == "indeterminate"` 写中文文案

**收紧风险:** 删 `| string` / 改 Record 类型参数会让一些历史宽类型代码报错 — 按报错位置逐一补 case 即可(这正是我们要的效果)。

### D6:F3 UI 用 `antd Alert type="info"`(不是 warning)
- `error_consistency` 维度降级 = 系统主动告知,不是告警;用 `info`
- 投标人详情 Drawer 顶部提示条:同理用 `info` 色
- **为什么不用 warning?** warning 色(橙)已是 medium 风险 + `needs_password` 提示共用,再塞一个"识别信息缺失"会色彩过载

### D7:ROLE_KEYWORDS 三处副本**降级同步**,role_keywords.py 为 SSOT
独立 reviewer 指出原"三处集合完全相等"约束**不可实现**:
- `prompts.py:12-25` 是自然语言描述(`pricing: 报价清单 / 工程量清单 / 商务标 / 投标报价`),没有可靠的"提取关键词 set"的解析规则
- `rules_defaults.py:64-72` pricing 故意用**短子串** `["报价", "清单", "工程量"]`(覆盖更广的 admin 默认语义),跟 `role_keywords.py` 的**复合词** `["投标报价", "报价清单"]` 故意不相等,强制相等会破坏 admin 默认覆盖范围
- `rules_defaults.py:71` 事实上已有 `authorization` 条(只是 keywords 列表为 `["授权", "委托"]` 缺 `"授权委托书"`),先前 proposal 措辞"缺整条"事实错误

降级后的约束:
1. **SSOT**: `role_keywords.py::ROLE_KEYWORDS` 是权威 — 关键词加减从这里开始
2. **key 集合一致**:三处对 9 种 role 的 key 完全相同(本次顺手给 `rules_defaults.py` 补 `"授权委托书"` 这一词,不是整条)
3. **value 非空**:三处每个 role 的关键词列表都非空
4. **不约束 value 相等**:`rules_defaults.py` 可以是 `role_keywords.py` 词集的**子串覆盖**(短子串语义更广,接受);`prompts.py` 自然语言描述**不进机械化测试**,只在 docstring 标注"更新关键词时需同步 review"
5. L1 测试 `test_role_keywords_3way_sync` 实现为:
   - `set(role_keywords.ROLE_KEYWORDS.keys()) == set(rules_defaults.ROLE_KEYWORDS.keys())` ✓
   - `all(len(v) > 0 for v in rules_defaults.ROLE_KEYWORDS.values())` ✓
   - prompts.py 不覆盖
6. **合并成 SSOT 是技术债**,作为 follow-up 留给后续独立 change

**为什么不强求 value 相等?** 违背 `rules_defaults.py` 的"admin 默认值用短子串覆盖广"设计意图;且测试无法自动校验 `prompts.py` 的自然语言描述。弱约束 + 人工 review 比假强约束可信。

### D8:`AnalysisStatusResponse.report_ready` 用"当前 version 下 `analysis_reports` 行是否存在"判定
```python
report_ready = (await session.scalar(
    select(AnalysisReport.id).where(
        AnalysisReport.project_id == pid,
        AnalysisReport.version == current_version,
    )
)) is not None
```
- judge_and_create_report 完成 = 插入 AnalysisReport 行成功 = report_ready
- 不用"判 agent_tasks 全终态"判断,因为 agent 完成到 judge 完成之间还有一段 window

### D10:`report_ready` 与 `project.status` 存在短暂不一致,以 `report_ready` 为权威
`judge_and_create_report` 执行顺序(见 detect-framework spec 步骤 9 → 10):
1. INSERT AnalysisReport 行 → `report_ready` 立刻变 true
2. UPDATE projects.status='completed' → 稍后一次 session.commit 才持久化

两步之间的 ~几十毫秒窗口里,客户端若同时轮询 `/analysis/status` 会看到 `report_ready=true` + `project_status='analyzing'` 的短暂不一致。

**决策:前端 SHOULD 以 `report_ready` 为拿报告的权威判据,不看 project_status**:
- `report_ready=true` → 可以安全拉 `/reports/{v}`
- `project_status='completed'` → 下一次轮询就会刷新,不是权威状态转换触发器

spec/detect-framework 的 `report_ready` scenario 里加一条说明,避免前端按 project_status 判定产生 bug。

### D9:FileTree 折叠规则
- **只折叠归档行本身 + 它的子文件树**;非归档的真文档平铺不动
- `defaultActiveKey={[]}` 默认全折叠
- Label 格式:`"📦 原始压缩包 ({archives.length} 个)"`
- 展开后显示:每个归档行 + 它的 `parse_error`(审计文本) + 它的子文件(复用现有展示)

**为什么不区分单/多归档显示?** 统一折叠更一致,单个包也折叠不啰嗦。

## Risks / Trade-offs

- **[R1] `risk_level=indeterminate` 打破前端若干处"硬匹配三值"的代码** → 缓解:按 D5 类型收紧(删 `| string` 逃生门 + Record 类型参数改 RiskLevel + 删运行期 `?? RISK_META.low` 兜底),漏改会真报错;L3 测试覆盖新 Tag 渲染
- **[R2] "证据不足"误标干净项目** → 可以接受(D1 副作用);若后续反馈多,加阈值 3 类"干净型 agent"(如 metadata_time/price_consistency 这类 "没异常 == 0" 的 agent)不计入判定
- **[R3] ROLE_KEYWORDS 三处副本漂移** → 缓解:本次加 CI lint 脚本 `backend/tests/unit/test_role_keywords_3way_sync.py` 断言三副本 key/value 集合一致;人工改一处漏改另一处会在 L1 fail
- **[R4] identity_info_status 计算逻辑变更影响现有测试** → 缓解:`identity_info` 当前查询的所有地方 grep 一遍,确保读取语义不变;`BidderResponse` 字段扩展是向前兼容的 superset
- **[R5] Word 模板变更可能影响现有导出 snapshot 测试** → 如果 snapshot 测试存在,更新预期 snapshot 并在 manual 阶段肉眼 verify 一次
- **[R6] 前端 `Collapse` 折叠后用户"找不到"压缩包入口** → 缓解:label 写"📦 原始压缩包 (N 个)"自解释;Collapse 默认 expand icon 明显

## Migration Plan

1. L1 实施 → 全绿
2. L2 实施 → 全绿
3. L3 实施 → 全绿(flaky 降 manual + 截图)
4. manual:起一个能触发 indeterminate 的简单项目 + 挂 identity_info=NULL 的 bidder,截 3 张图落 `e2e/artifacts/honest-detection-results-2026-04-23/`
5. Archive + git commit(CLAUDE.md 自动 commit 约定)
6. **前端与后端同步发布**:`indeterminate` 是新枚举,若单独发布后端会让旧前端看到 "risk_level 未知值" 走 fallback;需要前端一起上线

## Open Questions

- **Q1**:Word 模板 "indeterminate" 时的段落结构是否需要单独设计一个"证据不足"的小区块(比如不展示"风险说明"反而展示"为什么判定为证据不足")?—— 实施时看原模板结构决定;简单做就是改 `risk_level` 对应的文案串
- **Q2**:复核 API (`/reports/{v}/review`)的 `reviewer_decision` 字段当前支持 `confirm_high/confirm_medium/confirm_low/override_*` — 要不要支持复核员"这个 indeterminate 我覆盖成 low/medium/high"?—— 不在本次范围,留 follow-up;本次只保证前端不会因为读到 indeterminate 崩

## Context

3 个用户 bug 同根因"半成品契约":字段定义但下游不消费 / SSE publish 漏字段 / 算法维度对齐错位。两轮独立 reviewer 揭出 24 个 HIGH,主 session 反复修订 v1→v4 仍被找到 5 个新 HIGH 才真正合上。本次 design 将所有产品决策(D 系列)和实现策略(I 系列)集中下沉,impl 阶段直接 verify checklist。

**关键约束**(避 detect-template-exclusion 8 轮 reviewer 教训):
- spec delta 不下行号 / 不下 6 步顺序 / 每 Requirement 2 scenario 封顶
- 实现细节(watchdog 阈值、event publish 顺序、维度权重数值)放 design.md 不进 spec
- 决策表保持自洽 — 撤销的 D1/D4/D5/D7 不再隐性引用

## Goals / Non-Goals

**Goals**
- 修 3 个用户 bug + 9 个同根因对称性盲点(24 HIGH 中真根因部分)
- happy-path / failure-path / lifespan 三路径 SSE 协议完整,UI Tag 实时同步
- 2 个新 global Agent 落地新维度(price_total_match / price_overshoot),铁证级
- 前端 hook lift + 11→12 维兼容,零 SystemConfig 迁移

**Non-Goals**
- 不动 price_consistency / price_anomaly 既有算法逻辑(不引入跨场景短路机制)
- 不实现 direction='both' / 不分级超限阈值(决策 1A 简单优先)
- 不做 evidence_json schema_version 历史报告回算(F3 兼容兜底替代)
- 不动 useParseProgress 主体逻辑(只补一个 dead listener)
- 不重命名既有 UI key `price_ceiling`(决策 2A 零迁移;只改中文 label)

## Decisions

### 产品决策(已与用户对齐)

**D-Product-1 = A**:超限一律 ironclad(任一 bidder total > max_price)。理由:合规底线对齐,简单先做;follow-up 按运营反馈改阈值化。

**D-Product-2 = A**:UI 加 2 个新维度名 `price_total_match` + `price_overshoot`,**不重命名既有 `price_ceiling` UI key**(它继续指 anomaly engine);DEFAULT_RULES_CONFIG 加新行,新 2 维默认 weight=0(由 has_iron_evidence 短路升 high,不依赖权重)。理由:零 SystemConfig 迁移,生产环境老数据零变化。

**D-Product-3 = A**:既有 `price_ceiling` UI key 中文 label 从 "**报价天花板**" 改为 "**异常低价偏离**"。理由:既有 label 实际控制 anomaly engine 异常低价检测,新加 price_overshoot 后并列展示会让用户误改"报价天花板"修不到超限行为(产品级语义错位,reviewer H3)。纯 string 改,零行为变更,零 SystemConfig 迁移。

### 实现策略

**I-Backend-1 publish 顺序**:`judge.py:489` set status="completed" → commit → publish `project_status_changed{new_status:"completed"}` → publish `report_ready`(MUST status_changed before report_ready,避免前端"已完成 Tag 显示但报告入口缺失"的 race)。
*兜底*:前端 `report_ready` handler 同样 setProjectStatus("completed"),任一事件先到都能打 Tag(双保险)。

**I-Backend-2 crash 路径对称**:`engine.py:135 except Exception` 分支增 `await session.commit()` 设 status="ready",再 publish project_status_changed{ready} + publish error event(参 parser 侧 useParseProgress 既有 error 事件 schema)。

**I-Backend-3 scanner 路径补 publish**:`scanner.py:174` 既有 `project.status = "ready"` 已 commit,补 1 行 await publish project_status_changed{ready}。这条修补 project-status-sync spec 既有 generic Requirement 的违反,不增 Requirement(M1 归并)。

**I-Frontend-1 hook lift 位置**:`useDetectProgress(projectId)` 调用从 HeroDetectArea(L767)上提到 ProjectDetailPage 状态声明区(line 100 附近,所有 useState 之后,early-return 之前;避 violates rules of hooks)。HeroDetectArea / StartDetectButton 通过 props 接收 `detect / agentTasks / latestReport / refetch`(refetch prop chain 必须显式传到 StartDetectButton,既有 onStarted 闭包用)。

**I-Frontend-2 状态字段权威**:detect 期间 `detect.projectStatus` 是权威;`reloadProject()` 拉的 `project.status` 仅用于初次 mount / 切页回来兜底。Tag 用 `detect.projectStatus ?? project.status`(`??` 区分 null / 空串)。
*hook 初值*:`projectStatus` 初值从 `"draft"` 改为 `null`(避 `||` 短路反向 bug)。
*reloadProject 与 SSE 不再耦合*:report_ready handler 不再触发 reloadProject(避双 GET race)。

**I-Frontend-3 watchdog 阈值与触发条件**:
- 阈值 `35s`(≥ 2× HEARTBEAT_INTERVAL_S=15s + 5s tolerance)
- 跟踪 `lastBizEventAt`:仅 snapshot / agent_status / report_ready / project_status_changed / error 5 类业务事件更新;**heartbeat 不更新**
- 触发条件:active analysis 期间(projectStatus="analyzing"),lastBizEventAt 距今 ≥ 35s 启动 polling;biz 事件到达即停 polling
- **关键 acceptance**:SSE connected=true 但 35s 内无 biz 事件 → polling MUST 启动(避 impl 简化为"connected=false 时提前 polling" 漏掉假活症状)
- 阈值是实现细节,不进 spec

**I-Agent-1 price_total_match 触发**:消费既有 `anomaly_impl/extractor.aggregate_bidder_totals` 产出 BidderPriceSummary;遍历两两 bidder pair,任一 pair 的 `total_price` 完全相等(Decimal 相等比较)→ evidence["has_iron_evidence"]=True; score=100;evidence["pairs"]=[(bidder_a_id, bidder_b_id, total_price)]。
*与 price_consistency 责任划分*:price_consistency 看行级模式(尾数 / 单价匹配 / 系列关系),price_total_match 看 bidder 汇总值;两 detector 在"行也相同 total 也相同"场景同时命中是合理的(双重铁证),用户不会困惑(UI 各自维度独立显示)。
*known limitation*:跨币种 false positive — 项目大概率单币种,follow-up 加 currency 一致性 preflight。

**I-Agent-2 price_overshoot 触发**:消费 BidderPriceSummary + Project.max_price;任一 bidder.total_price > max_price(严格大于)→ evidence["has_iron_evidence"]=True; score=100;evidence["overshoot_bidders"]=[(bidder_id, total, ratio)]。
*preflight*:max_price=NULL or ≤0 → skip,写 OA 行 evidence{enabled:false, reason:"未设限价"}(对齐 detect-framework spec L460 "所有 global agent 必须写恰好一行 OA")。

**I-Agent-3 不动 price_consistency 的 scorer**:之前 v1-v3 设计的 `force_ironclad_subdims 短路` 完全删除;has_iron_evidence 由 Agent 自己在 run() 内 set,通过 OverallAnalysis.evidence_json 写库;judge.py 既有铁证短路逻辑(读 evidence["has_iron_evidence"])直接生效,无需新机制。

**I-Weight-1 权重重平衡(只动 code 默认;数值 verified against `judge.py` DIMENSION_WEIGHTS)**:
| 维度 | 旧 | 新 | Δ |
|---|---|---|---|
| text_similarity | 0.12 | 0.12 | — |
| section_similarity | 0.10 | 0.10 | — |
| structure_similarity | 0.08 | 0.08 | — |
| metadata_author | 0.10 | 0.10 | — |
| metadata_time | 0.08 | 0.08 | — |
| metadata_machine | 0.10 | 0.10 | — |
| price_consistency | 0.10 | 0.10 | — |
| price_anomaly | 0.07 | 0.07 | — |
| error_consistency | 0.12 | 0.10 | **-0.02** |
| style | 0.08 | 0.07 | **-0.01** |
| image_reuse | 0.05 | 0.02 | **-0.03** |
| price_total_match | — | 0.03 | **+0.03** |
| price_overshoot | — | 0.03 | **+0.03** |
| **和** | **1.00** | **1.00** | ✓ |

**I-Weight-2 SystemConfig 不动**:DEFAULT_RULES_CONFIG 既有 dim weight 不变(决策 2A 零迁移);新 2 维 dim 默认 weight=0(由 has_iron_evidence 短路升 high,不依赖权重)。
*spec 显式注*:admin-rules spec 写明"price_total_match / price_overshoot 维度命中信号通过 has_iron_evidence 短路升 high,不依赖 SystemConfig weight 配置"(避 reviewer 怀疑权重为 0 是 bug)。

**I-UI-1 雷达图 11→12 维兼容**:老报告 OA 无新维度行 → 维度列表渲染 `?? "未检测"`;新报告 evidence{enabled:false} → 渲染对应 reason(未设限价 / 数据缺失);命中 → Tag color="error" 文字"超限" / "两家总价完全相同"。

**I-UI-2 既有 label 修正**:`AdminRulesPage.tsx:45` 中文 label 字典 `price_ceiling: "报价天花板"` → `price_ceiling: "异常低价偏离"`。仅前端中文 string 改,UI key / 后端 mapper / SystemConfig 字段名全部不变。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| publish 顺序竞态(status_changed 与 report_ready) | I-Backend-1 锁 MUST 顺序 + I-Frontend-2 双保险 handler |
| watchdog 阈值不当(假活 / 误启 polling) | I-Frontend-3 业务事件追踪 + 35s ≥ 2×heartbeat + 关键 acceptance 显式锁 |
| lift hook 破坏 props 链路 | I-Frontend-1 显式列 refetch prop chain;调用位置在 state 区 |
| 11→12 维既有断言连带断 | G 部分巡检 8 处硬编码 |
| price_total_match 跨币种 false positive | known limitation,follow-up 加 currency 一致性 |
| 老 SystemConfig 用户已 admin 改权重 | I-Weight-2 新 2 维不依赖权重(has_iron_evidence 短路);SystemConfig 不动 |

## Migration Plan

1. impl 按 tasks 顺序改,提交粒度对齐 task(细颗粒度便于 review 定位)
2. 部署无需迁移步骤;既有 SystemConfig 行为不变;既有报告 OA 无新维度行 → UI 渲染兜底
3. Rollback:回滚 commit;不改 schema / DB 约束,无遗留状态

## Open Questions

无。3 个产品决策与用户对齐(2026-04-27),其余技术决策在 I 系列已下沉。

## Self-review Checklist(propose 前)

- [x] 4 轮 reviewer 24+5 HIGH 全部映射到 task 或 known limitation
- [x] 权重和验证 = 1.00
- [x] spec delta 3 capability 不重复(M1 归并)
- [x] watchdog 阈值 35s ≥ 2× heartbeat + tolerance
- [x] hook 初值改 null,Tag 用 ?? 不用 ||
- [x] publish 顺序锁 MUST status_changed before report_ready
- [x] scanner publish 不再 D13 拒做(spec 违反点修补)
- [x] price_ceiling UI label 改名修语义错位
- [x] 11→12 维既有 8 处硬编码列入 task
- [x] 工作量 4-5 天(诚实)

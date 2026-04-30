## ADDED Requirements

### Requirement: TenderDocument 数据模型

系统 MUST 支持项目级招标文件 (tender) 1..N 入库,与投标人 (bidder) 解耦。

`TenderDocument` 表 SHALL 含字段:`id` / `project_id` (FK projects.id) / `file_name` / `file_path` / `md5` (16 字节前缀,用作项目内去重 unique key) / `parse_status` (enum: `pending` / `parsing` / `extracted` / `failed`) / `created_at` / `deleted_at` (软删除)。

`BidDocument` 表的 `file_role` 字段 MUST NOT 包含 `"tender"` 值;tender 走独立表,**不**污染 BidDocument 的 18 个消费方。

#### Scenario: 项目可关联多份招标文件

- **WHEN** 同一 project_id 下上传 2 份不同招标文件 (md5 不同)
- **THEN** TenderDocument 表写入 2 行,均关联同一 project_id

#### Scenario: 项目内招标文件 md5 去重

- **WHEN** 同一 project_id 下重复上传相同招标文件 (md5 相同)
- **THEN** 系统 MUST 拒绝重复上传 (返回 409),不写入第二行

#### Scenario: BidDocument.file_role 拒绝 "tender" 值

- **WHEN** 任何代码路径试图把 BidDocument.file_role 设为 "tender"
- **THEN** 系统 MUST 拒绝该写入或值校验失败 (留 L1 单测保护)

---

### Requirement: segment_hash 段级哈希索引

`DocumentText` 表 SHALL 加 `segment_hash VARCHAR(64) NULL` 字段,存归一化后段文本的 SHA256 hexdigest。

归一化算法 MUST 复用 `text_sim_impl.tfidf._normalize`(NFKC + `\s+→' '` + strip),保证与 `text-sim-exact-match-bypass` 的 hash 旁路口径统一。

段长度归一化后 < 5 字符的段 MUST 设 segment_hash = NULL(防止"投标人:"等通用短段大量假命中)。

历史 DocumentText 行 segment_hash 默认 NULL;新检测时 baseline_resolver MUST 跳过 NULL 段,不参与 baseline 比对。

#### Scenario: parser 切段后批量计算 segment_hash

- **WHEN** parser pipeline 完成段落抽取并入库 DocumentText
- **THEN** 系统 SHALL 对每段 (归一化后字符长度 ≥ 5) 计算 SHA256 hexdigest 并写入 segment_hash 字段

#### Scenario: 短段 segment_hash 守门

- **WHEN** 一段归一化后字符长度为 4 (如"投标人:")
- **THEN** segment_hash MUST = NULL,baseline_resolver 跳过

#### Scenario: 历史段落 lazy 处理

- **WHEN** detector run 时遇到 segment_hash = NULL 的段
- **THEN** baseline_resolver MUST 跳过该段(不阻塞 detector,fail-soft)

---

### Requirement: baseline_resolver 三级降级判定

新建模块 `services/detect/baseline_resolver.py`,封装"基线识别"的三级降级判定。

接口契约:`resolve_baseline(session, project_id, dimension, raw_pairs) -> BaselineResolution`,返回 `(excluded_pair_ids: set, baseline_source: str, warnings: list)`。

`baseline_source` MUST ∈ `{"tender", "consensus", "metadata_cluster", "none"}`,优先级 `tender > consensus > metadata_cluster > none`(同段多 source 命中取最强)。

三级降级规则:

- **L1**:project 关联 ≥1 份 `parse_status='extracted'` 的 TenderDocument 时,段对 (a, b) 的双方 segment_hash 同时 ∈ tender hash 集合 → `baseline_source='tender'`,加入 `excluded_pair_ids`(L1 优先于投标方数量门槛 —— 即使投标方 ≤2,有 tender 仍走 L1)
- **L2**:无可用 tender + project 投标方数量 N ≥ 3 时,某 segment_hash 在 ≥3 distinct bidder 的应标段中出现 → 涉及该 hash 的段对 → `baseline_source='consensus'`,加入 `excluded_pair_ids`
- **L3**:无可用 tender + N ≤ 2 时,`baseline_source='none'`,`excluded_pair_ids=空集`,`warnings` 含 `"baseline_unavailable_low_bidder_count"`;**ironclad 触发逻辑保留原行为,L3 不抑制 ironclad**(用户产品立场:基线缺失 ≠ 信号无效)

共识计数 MUST 按 `file_role` 分组(同一 hash 在 `technical` 标段命中 vs `company_intro` 标段命中分别计数);file_role ∈ `{'unknown', 'other'}` 的段 MUST NOT 参与共识计数(分类噪音不应触发模板剔除)。

**BOQ 维度例外**:`dimension ∈ {'price_consistency', 'price_anomaly'}` 时,baseline_resolver MUST 仅走 L1 tender 路径;**L2 共识 MUST NOT 适用**(原因:招标方下发同一份工程量清单给多家应标方是合法行为,共识阈值会把它们全部误剔成"模板"变零分;详见 design D5)。

**SQL 拼装归属契约**(R6 第三轮 NM2):`price_anomaly` 维度的 `excluded_price_item_ids` 集合查询(`SELECT id FROM price_items WHERE project_id=:pid AND boq_baseline_hash IN :tender_hashes`)MUST 由 baseline_resolver 模块负责;detector(`price_anomaly.run()`)只透传调用 `aggregate_bidder_totals(excluded_price_item_ids=baseline_resolver.get_excluded_price_item_ids(...))`,**MUST NOT** 在 detector 内直接拼装 SQL(避免 baseline 业务逻辑泄漏到 detector 层)。

#### Scenario: L1 tender hash 命中

- **WHEN** project 有 1 份 extracted TenderDocument,段 X 的 segment_hash ∈ tender hash 集合
- **THEN** 任何含段 X 的 PC pair MUST 进 excluded_pair_ids,baseline_source='tender'

#### Scenario: L2 跨投标人共识 ≥3 命中

- **WHEN** 无 tender,project 有 5 家投标方,某 segment_hash H 在 A/B/C/D/E 5 家中的 3 家 (file_role=company_intro) 命中
- **THEN** 涉及段 H 的 PC pair MUST 进 excluded_pair_ids,baseline_source='consensus'

#### Scenario: L2 共识不达阈值不剔除

- **WHEN** 无 tender,某 segment_hash H 仅在 A/B 2 家命中
- **THEN** 涉及段 H 的 PC pair MUST NOT 进 excluded_pair_ids,baseline_source='none'

#### Scenario: L3 投标方 ≤2 警示但不抑制 ironclad

- **WHEN** 无 tender,project 仅 2 家投标方,某段对 ≥50 字 exact_match
- **THEN** baseline_source='none',warnings 含 'baseline_unavailable_low_bidder_count',excluded_pair_ids=空集;is_ironclad MUST 保留原触发行为(若原条件成立则=True)

#### Scenario: tender 命中优先于投标方数量门槛

- **WHEN** project 仅 2 家投标方,**有** 1 份 extracted tender,某段 hash 命中 tender 集合
- **THEN** baseline_source='tender'(走 L1,不退化到 L3 警示),涉及段的 PC pair 进 excluded_pair_ids

#### Scenario: 共识按 file_role 分组

- **WHEN** segment_hash H 在 technical 标段命中 A/B/C 3 家,在 company_intro 标段命中 A/B 2 家
- **THEN** technical 命中触发共识,company_intro 不触发

#### Scenario: unknown file_role 不参与共识

- **WHEN** segment_hash H 在 file_role='unknown' 段命中 A/B/C 3 家
- **THEN** baseline_source='none'(不触发 consensus,unknown/other 是分类噪音不应被认作模板)

#### Scenario: tender + cluster 多 source 命中取最强

- **WHEN** 段 X 同时被 tender hash 命中 + metadata_cluster 模板簇命中
- **THEN** baseline_source='tender'(优先级最高)

---

### Requirement: 4 高优 detector 接入 baseline 注入点

`text_similarity` / `section_similarity` / `price_consistency` / `price_anomaly` 4 个 detector MUST 接入 `baseline_resolver`,在产出 PairComparison 前查询 baseline。

ironclad 触发条件 MUST 在原有规则之上叠加 baseline 检查:任一原 ironclad 触发条件成立时,系统 SHALL 检查相关段对的 `baseline_source` —— 若 `baseline_source ∈ {"tender", "consensus"}` 则该段对 MUST 从 ironclad 触发集中剔除。

`baseline_source = "metadata_cluster"`(已有 detect-template-exclusion 路径)继续生效,行为不变。

`baseline_source = "none"`(含 L3 投标方 ≤2 场景) → ironclad 触发集 MUST 保留原触发条件结果(detector 单维度仍可独自顶铁证;基线缺失 ≠ 信号无效);仅 evidence_json.warnings 标记 'baseline_unavailable_low_bidder_count' 给前端展示警示。

PC 内含多个 exact_match 段时,**仅未命中 baseline 的段**计入 ironclad 触发判定(部分命中 baseline 不豁免整 PC 的 ironclad)。

evidence_json MUST 加顶级字段 `baseline_source ∈ {"tender", "consensus", "metadata_cluster", "none"}`,缺失字段时前端 fallback 渲染 "none"。后端读取老 PairComparison(无 evidence_json.baseline_source 字段)MUST NOT 报错(`evidence_json.get('baseline_source', 'none')` 默认值)。

**段级 baseline 标记**(供前端 H7 分段渲染):evidence_json.samples[i] MUST 加 `baseline_matched: bool` + `baseline_source: str ∈ {tender, consensus, none}` 段级字段(由 `aggregator.build_evidence_json` 写入);前端 TextComparePage / DimensionRow MUST 直接读 samples[i].baseline_matched 决定该段灰底/Tag,**不复算 hash**;PC 顶级 baseline_source 取所有命中段的最强 source(供 Badge 渲染用)。

#### Scenario: text_similarity ≥50 字 exact_match + tender 命中不升 ironclad

- **WHEN** 段对 (a, b) ≥50 字 exact_match 且 baseline_source='tender'
- **THEN** is_ironclad MUST = False,evidence_json.baseline_source='tender'

#### Scenario: text_similarity ≥50 字 exact_match + 无 baseline 仍升 ironclad

- **WHEN** 段对 (a, b) ≥50 字 exact_match 且 baseline_source='none'(投标方 ≥3 但共识未命中)
- **THEN** is_ironclad MUST = True(原行为不变),evidence_json.baseline_source='none'

#### Scenario: section_similarity 章节级 baseline 命中

- **WHEN** 章节标题 hash 在 tender 章节集合命中
- **THEN** 该章节对 MUST 从 ironclad 触发集剔除,evidence_json.baseline_source='tender'

#### Scenario: price_consistency BOQ 项级 baseline 命中

- **WHEN** 段对引用的 PriceItem 的 boq_baseline_hash ∈ tender BOQ hash 集合
- **THEN** 该 PC pair MUST 从 ironclad 触发集剔除,baseline_source='tender'

#### Scenario: L3 投标方 ≤2 仍可独自顶铁证

- **WHEN** 无 tender + 仅 2 家投标方,text_similarity 检测出 ≥50 字 exact_match
- **THEN** is_ironclad MUST = True(原触发行为不变),evidence_json.baseline_source='none',evidence_json.warnings 含 'baseline_unavailable_low_bidder_count'(供前端展示警示条)

#### Scenario: PC 内部分段命中 baseline 不豁免整 PC

- **WHEN** PC pair 含 5 段 exact_match,2 段 baseline_source='tender' 命中、3 段未命中,3 个未命中段中有 ≥1 段归一化长度 ≥50
- **THEN** is_ironclad MUST = True(按未命中段判定);evidence_json.baseline_source 取最强 source(此处='tender')但 ironclad 仍触发;**UI 渲染分段判定**:命中 baseline 的 2 段 MUST 渲染灰底 + "模板段(招标文件)" Tag,未命中的 3 段 MUST 按原 simBgColor 渲染并贴铁证 Tag;**报告页 Badge 按 PC 级 baseline_source 取最强**显示蓝色"招标文件基线"(段级歧义解析:Tag/灰底按段判定,Badge 按 PC 取最强)

#### Scenario: 后端读老 PairComparison 兼容

- **WHEN** reports API 读取一个 v=N 老版本 PairComparison,其 evidence_json 不含 baseline_source 字段
- **THEN** API MUST NOT 抛 KeyError;返回时 baseline_source 默认 'none'

---

### Requirement: BOQ 项级 baseline hash

`PriceItem` 表 SHALL 加 `boq_baseline_hash VARCHAR(64) NULL` 字段。

BOQ baseline hash key MUST = `sha256(nfkc_strip(项目名) + '|' + nfkc_strip(描述) + '|' + nfkc_strip(单位) + '|' + decimal_normalize(工程量))`,**不含**单价/合价/总价。

`decimal_normalize` MUST 用 `Decimal(str(value)).normalize()` 去尾随零("1.0" / "1" / "1.000" hash 一致)。

多份 tender xlsx 的 BOQ 行 hash MUST 合进项目级同一集合,不区分文件归属。

#### Scenario: BOQ hash 不含价格

- **WHEN** 应标方 A 单价填 100 元,应标方 B 单价填 120 元,但项目名/描述/单位/工程量完全相同
- **THEN** 两家 boq_baseline_hash MUST 相等(忽略价格差异)

#### Scenario: 工程量精度归一化

- **WHEN** A 行工程量 "1",B 行工程量 "1.0",C 行工程量 "1.000",其余字段相同
- **THEN** 三行 boq_baseline_hash MUST 相等

#### Scenario: 多份 BOQ xlsx 合并基线

- **WHEN** project 关联 2 份 tender xlsx,各含 5 行 BOQ
- **THEN** baseline_resolver 加载的 BOQ hash 集合 MUST 含 10 个 hash(合并去重)

#### Scenario: BOQ 跨投标人共识不剔除(L2 不适用)

- **WHEN** 无 tender,4 家应标方均填同一份招标方下发工程量清单(项目名+描述+单位+工程量四元组完全一致),boq_baseline_hash 在 4 家完全相同
- **THEN** baseline_resolver 对 dimension='price_consistency' 维度 MUST 返回 baseline_source='none' + excluded_pair_ids=空集(L2 共识不适用 BOQ);price_consistency 维度照常计分,**不**降到零分

---

### Requirement: baseline_resolver 与 template_cluster 协同契约

baseline_resolver 与 `template_cluster._apply_template_adjustments` MUST 遵循"生产者 + 纯执行器"职责划分:

- **生产者(baseline_resolver)** SHALL 暴露 `produce_baseline_adjustments(session, project_id, dimension, raw_pairs) -> list[Adjustment]`,输出 `Adjustment` list,reason ∈ {`tender_match`, `consensus_match`}
- **纯执行器(template_cluster)** SHALL 扩 `_apply_template_adjustments` 签名加 `extra_adjustments: list[Adjustment] = []` 参数,内部把 metadata_cluster 自产的 + baseline_resolver 喂入的 adjustments **合并**(同 PC.id 取最强 source);**source priority 映射**(数值越大越强):`tender_match=3` > `consensus_match=2` > `template_cluster_excluded=1` > `template_cluster_downgraded=1` > 其余 metadata_cluster reason `=1` > `none=0`;同 PC.id 多 adjustment 命中时仅保留 priority 最高的一条,丢弃低优先级 adjustment(避免重复应用 score=0)。**铁证豁免覆盖语义**:若原 metadata_cluster 路径产 `template_cluster_downgrade_suppressed_by_ironclad`(铁证豁免不剔除,priority=1)同时被 tender_match 命中(priority=3),则被 tender_match 覆盖,is_ironclad MUST = False(tender 命中即从 ironclad 触发集剔除,豁免意图不再保留 —— 这是 D14 设计本意:tender 是更确定的模板基线信号,优先于元数据指纹的豁免逻辑)
- template_cluster **不新增** if/elif baseline 业务分支;reason 枚举仅由调用方决定

`tender_match` / `consensus_match` 的 score 语义:
- `score = 0.0`(与 metadata_cluster 一致)
- `is_ironclad = False`(从触发集剔除)
- `evidence_extras.template_cluster_excluded = True`(复用现有标记)
- `evidence_extras.baseline_source ∈ {tender, consensus}` 区分来源

`Adjustment.reason` 枚举 MUST 扩展为 `{template_cluster_excluded, template_cluster_downgraded, template_cluster_excluded_all_members, template_cluster_downgrade_suppressed_by_ironclad, def_oa_aggregation_after_template_exclusion, tender_match, consensus_match}`(原 5 + 新 2)。

**职责变更影响声明**:本 change 实质上修改了 `template_cluster._apply_template_adjustments` 函数语义(从"metadata 簇专属"扩到"通用 adjustments 执行器"),但通过新增 `extra_adjustments` 入参保持向后兼容(不传时行为完全等价于 detect-template-exclusion 归档时)。本 spec 用 ADDED 格式而非 MODIFIED 是因为:① 函数对外契约扩展不缩减 ② 原 metadata_cluster 路径行为完全保留 ③ MODIFIED 复制原 detect-template-exclusion 整段会引入冗余无新信息。

#### Scenario: tender adjustment 与 metadata_cluster adjustment 同 PC 取最强 source

- **WHEN** 段 X 同时被 tender hash 命中 + 所在 PC 也被 metadata_cluster 模板簇命中
- **THEN** `_apply_template_adjustments` 应用合并后,该 PC 的 evidence_extras.baseline_source='tender'(优先级最高);adjustment 列表中仅保留 1 条 reason='tender_match'(被 metadata_cluster 自产的 'template_cluster_excluded' 覆盖)

#### Scenario: 旧调用兼容(extra_adjustments 默认 [])

- **WHEN** 任何代码调用 `_apply_template_adjustments(pcs, oas, clusters)` 不传 extra_adjustments
- **THEN** 函数行为 MUST 完全等价于 detect-template-exclusion 归档时(只处理 metadata 簇,不读 baseline)

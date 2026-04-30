## ADDED Requirements

### Requirement: 报告页基线状态 Badge

`ReportPage` 头部 SHALL 显示基线状态 Badge,标识本次检测使用的 baseline 类型。

Badge 渲染规则:
- L1 (有 tender):蓝色背景 `#eef3fb` + 文案"招标文件基线"
- L2 (无 tender + ≥3 投标方共识):琥珀色背景 `#fcf3e3` + 文案"共识基线"
- L3 (无 tender + ≤2 投标方):中性灰背景 `#f5f7fa` + 文案"警示模式"

数据源:`evidence_json.baseline_source` 在该次检测的所有 PC 中聚合(取最强 source);兜底 `none` 时显示 L3 灰色"无基线"。

老版本检测(v_n 该字段缺失)前端 fallback 渲染"无基线信息"中性灰 Badge。

Badge MUST 受前端 feature flag 控制:flag=false 时不渲染。

#### Scenario: L1 tender 基线渲染蓝色 Badge

- **WHEN** flag=true,本次 evidence 中 ≥1 PC 的 baseline_source='tender'
- **THEN** 头部 Badge 渲染蓝色 + 文案"招标文件基线"

#### Scenario: L2 共识基线渲染琥珀 Badge

- **WHEN** flag=true,所有 PC baseline_source ∈ {'consensus', 'metadata_cluster', 'none'},无 'tender'
- **THEN** Badge 琥珀色 + 文案"共识基线"

#### Scenario: L3 警示渲染中性灰 Badge

- **WHEN** flag=true,project 投标方 ≤2,所有 PC baseline_source='none'
- **THEN** Badge 中性灰 + 文案"警示模式"

#### Scenario: 老版本无 baseline_source 字段 fallback

- **WHEN** flag=true,访问历史 v_n 报告,evidence 不含 baseline_source
- **THEN** Badge 中性灰 + 文案"无基线信息"

#### Scenario: feature flag 关闭隐藏 Badge

- **WHEN** flag=false 访问任何报告
- **THEN** Badge MUST NOT 渲染

---

### Requirement: 维度行模板段标识 Tag

`DimensionRow` 在维度详情展开时 SHALL 渲染模板段标识 Tag,区分 baseline 来源。

Tag 渲染规则:
- baseline_source='tender' → Tag color="blue" + 文案"模板段(招标文件)"
- baseline_source='consensus' → Tag color="orange" + 文案"模板段(共识)"
- baseline_source='metadata_cluster' → Tag color="default" + 文案"模板段(元数据)"
- baseline_source='none' 或缺失 → 不渲染 Tag(原行为)

Tag MUST 紧跟段对相似度数值显示,在铁证 Tag(若存在)之前。

模板段不参与 ironclad 触发集 → DimensionRow 的铁证 Tag MUST NOT 显示在已剔除的段对上。

#### Scenario: tender 命中段渲染蓝 Tag

- **WHEN** 维度展开,某段对 baseline_source='tender'
- **THEN** 该行渲染 Tag color="blue" "模板段(招标文件)",**不**渲染铁证 Tag

#### Scenario: consensus 命中段渲染橙 Tag

- **WHEN** 段对 baseline_source='consensus'
- **THEN** 渲染 Tag color="orange" "模板段(共识)"

#### Scenario: 无 baseline 段保持原行为

- **WHEN** 段对 baseline_source='none' 且原 ironclad 触发条件成立
- **THEN** SHALL 渲染铁证 Tag(原行为不变),不渲染模板段 Tag

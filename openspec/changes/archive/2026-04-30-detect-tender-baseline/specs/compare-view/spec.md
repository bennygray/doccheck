## ADDED Requirements

### Requirement: 双栏对比模板段灰底渲染

`TextComparePage` 和 `ComparePage`(及变体 `MetaComparePage` / `PriceComparePage`) SHALL 对模板段(`baseline_source ∈ {'tender', 'consensus', 'metadata_cluster'}`)渲染灰色背景。

灰色色值 MUST = `rgba(138,145,157,0.08)`(复用 `tokens.ts` 既有 `textTertiary` token,**不新增色值**)。

灰底 MUST 优先于既有相似度 simBgColor 渲染(模板段不再按琥珀色四档高亮)。

模板段 SHALL 在段落行首贴一个小 Tag(color="default" + 文案):
- baseline_source='tender' → "模板段(招标文件)"
- baseline_source='consensus' → "模板段(共识)"
- baseline_source='metadata_cluster' → "模板段(元数据)"

模板段 Tag + 灰底 MUST 受前端 feature flag `VITE_TENDER_BASELINE_ENABLED` 控制:flag=false 时回退到原 simBgColor 琥珀色四档渲染。

#### Scenario: tender 模板段灰底渲染

- **WHEN** flag=true,双栏对比中段 X baseline_source='tender'
- **THEN** 段 X 背景 = `rgba(138,145,157,0.08)`,行首贴 Tag "模板段(招标文件)"

#### Scenario: consensus 模板段灰底渲染

- **WHEN** flag=true,段 X baseline_source='consensus'
- **THEN** 段 X 灰底 + Tag "模板段(共识)"

#### Scenario: 真抄袭段保持琥珀色

- **WHEN** flag=true,段 X baseline_source='none' 且 sim ≥ 90%
- **THEN** 段 X 渲染琥珀色 `rgba(194,124,14,0.38)`(原行为不变),不贴模板 Tag

#### Scenario: feature flag 关闭回退原渲染

- **WHEN** flag=false,段 X 任何 baseline_source
- **THEN** SHALL 按原 simBgColor 琥珀色四档渲染,不贴模板 Tag(行为与 change 前完全一致)

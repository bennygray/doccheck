## MODIFIED Requirements

### Requirement: 角色关键词兜底规则

系统 SHALL 在 `app/services/parser/llm/role_keywords.py` 维护 `ROLE_KEYWORDS: dict[str, list[str]]` 常量,用于 LLM 失败时的"正文关键词兜底 + 文件名关键词兜底"两级匹配。

- 8 个角色各配一组关键词(pricing / technical / construction / unit_price / bid_letter / qualification / company_intro / authorization);第 9 个角色 `other` 为默认兜底,无需关键词
- 提供两个入口函数:
  - `classify_by_keywords(file_name: str) -> str | None`:对文件名做子串包含匹配(不区分大小写),按字典声明顺序遍历,首次命中即返回,全未命中返回 `None`
  - `classify_by_keywords_on_text(text: str) -> str | None`:对正文首段文本做子串包含匹配(不区分大小写),规则同上
- **[honest-detection-results]** ROLE_KEYWORDS 实际存在 3 处副本,本 change 采取**降级同步约束**(不强求值集合完全相等):
  1. `app/services/parser/llm/role_keywords.py` — runtime 两级兜底匹配入口(**SSOT,关键词加减从这里开始**)
  2. `app/services/parser/llm/prompts.py` — LLM 系统 prompt 中"角色→主要关键词"的说明性描述(**不进机械化测试**,改关键词时需 docstring 标注并人工 review 同步)
  3. `app/services/admin/rules_defaults.py` — admin UI 管理员可配置关键词的默认值(**允许用短子串以扩大覆盖范围**,与 role_keywords.py 的复合词策略不同)
- 同步约束:
  - (a) 三处对 9 种 role 的 key 集合完全一致
  - (b) 每处每个 role 的 keywords list 非空
  - (c) **不要求 value 集合相等**(rules_defaults.py 短子串与 role_keywords.py 复合词故意不等是 admin 默认覆盖语义)
- **[honest-detection-results]** 行业术语补充(10 个新词加到 role_keywords.py,rules_defaults.py 可酌情加对应短子串):
  - `pricing`: 增加 `价格标`、`开标一览表`
  - `qualification`: 增加 `资信标`、`资信`、`业绩`、`类似业绩`
  - `company_intro`: 增加 `企业简介`
  - `construction`: 增加 `施工进度`、`进度计划`
- **[honest-detection-results]** `rules_defaults.py:71` 的 `authorization` keywords 当前为 `["授权", "委托"]`,补一项 `"授权委托书"`(之前提案误称"整条缺失",实为少一词)
- 本期不支持管理员动态维护(D2 决策);C17 升级为 DB + admin UI(admin_rules capability);三副本合并 SSOT 留 follow-up

#### Scenario: 角色关键词常量存在

- **WHEN** 导入 `ROLE_KEYWORDS`
- **THEN** 字典含 8 个角色键,每个值为非空字符串列表

#### Scenario: 文件名命中关键词返回对应角色

- **WHEN** 文件名 "投标报价.xlsx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"pricing"`(命中关键词 "报价")

#### Scenario: 文件名未命中返回 None

- **WHEN** 文件名 "XYZ.docx" 不含任何关键词
- **THEN** `classify_by_keywords` 返回 `None`(调用方据此决定走下一层兜底或兜底到 "other")

#### Scenario: 正文命中关键词返回对应角色

- **WHEN** 正文首段"本公司针对本次招标项目提交投标报价一览表如下",调用 `classify_by_keywords_on_text(text)`
- **THEN** 返回 `"pricing"`(命中关键词 "报价")

#### Scenario: 正文未命中返回 None

- **WHEN** 正文首段不含任何角色关键词
- **THEN** `classify_by_keywords_on_text` 返回 `None`

#### Scenario: 新增"价格标"术语命中 pricing

- **WHEN** 文件名 "XX 价格标.docx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"pricing"`

#### Scenario: 新增"资信标"术语命中 qualification

- **WHEN** 文件名 "XX 资信标.docx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"qualification"`

#### Scenario: 新增"类似业绩"术语命中 qualification

- **WHEN** 文件名 "类似业绩证明.docx" 或正文"公司完成过如下类似业绩",调用对应 classify 函数
- **THEN** 返回 `"qualification"`

#### Scenario: 新增"开标一览表"术语命中 pricing

- **WHEN** 文件名含 "开标一览表"
- **THEN** `classify_by_keywords` 返回 `"pricing"`

#### Scenario: 新增"企业简介"术语命中 company_intro

- **WHEN** 文件名 "企业简介.docx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"company_intro"`(原有表只有"企业介绍/公司简介/公司概况",不含"企业简介")

#### Scenario: 新增"施工进度"/"进度计划"术语命中 construction

- **WHEN** 文件名 "施工进度表.docx" 或 "进度计划.xlsx"
- **THEN** `classify_by_keywords` 分别返回 `"construction"`

#### Scenario: 两处可机械校验副本保持 key 同步

- **WHEN** L1 测试 `test_role_keywords_3way_sync` 比对 `role_keywords.py::ROLE_KEYWORDS` 和 `rules_defaults.py::ROLE_KEYWORDS`(prompts.py 不进测试,因其为自然语言描述无可靠提取规则)
- **THEN** 两处 key 集合完全相同;两处每个 role 的 keywords list 非空;**不**要求 value 集合相等(rules_defaults.py 可用短子串)

#### Scenario: rules_defaults.py 的 authorization 含授权委托书

- **WHEN** 读取 `admin/rules_defaults.py::ROLE_KEYWORDS["authorization"]`
- **THEN** 列表含 `授权委托书`、`授权`、`委托` 三项(change 前只有后两项)

#### Scenario: rules_defaults.py 允许短子串策略

- **WHEN** `role_keywords.py::ROLE_KEYWORDS["pricing"]` 含复合词 `投标报价`,而 `rules_defaults.py::ROLE_KEYWORDS["pricing"]` 含短子串 `报价`
- **THEN** 两者**都合法**,测试不 fail;本 change 不改 admin 默认的短子串覆盖策略

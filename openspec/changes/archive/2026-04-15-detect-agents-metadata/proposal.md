## Why

M3 里程碑第 5/9 个 change。C6 已建 detect-framework 注册 10 Agent 骨架(dummy `run()`);C7/C8/C9 已替换 `text_similarity` / `section_similarity` / `structure_similarity` 三个 Agent 的 dummy,剩 7 Agent 待落真实算法。C10 一次性替换 **3 个 metadata Agent**(`metadata_author` / `metadata_time` / `metadata_machine`)的 dummy `run()`,覆盖围标检测"元数据指纹"证据链。

合并理由(对齐 `docs/execution-plan.md` §3 C10):
- 共用数据源(`DocumentMetadata` 表,C5 已持久化 `author` / `last_saved_by` / `company` / `doc_created_at` / `doc_modified_at` / `app_name` / `app_version`)
- 同算法骨架(跨投标人的字段聚类/碰撞 + 精确匹配)
- UI 呈现耦合(合并展示为"元数据维度表")

## What Changes

### 数据层(C5 延伸,跨层扩)
- 新增 alembic `0007_add_document_metadata_template`:`document_metadata` 表加 `template VARCHAR(255) NULL` 列
- 扩 `backend/app/services/parser/content/__init__.py`:docx/xlsx `app.xml` 中 `Template` 字段提取并写入
- 扩 `backend/app/models/document_metadata.py`:`template: Mapped[Optional[str]]`
- 新增 `backend/scripts/backfill_document_metadata_template.py`:幂等回填脚本(照搬 C9 `backfill_document_sheets.py` 模板:单 doc 独立 session + 错误隔离 + `--dry-run` + 退出码)

### 检测层(C10 主体,不动框架)
- 新增子包 `backend/app/services/detect/agents/metadata_impl/`(9 文件):
  - `__init__.py` / `config.py`(env 读取 + flag) / `models.py`(evidence schema) / `normalizer.py`(NFKC+casefold+strip 共用归一化)
  - `extractor.py`(从 `DocumentMetadata` 批量 query → `{bidder_id: MetadataRecord}`)
  - `author_detector.py` / `time_detector.py` / `machine_detector.py`(3 子算法,纯程序化,零 LLM)
  - `scorer.py`(子维度合成 Agent 级 score,disabled 不参与归一化)
- 重写 `backend/app/services/detect/agents/metadata_author.py` / `metadata_time.py` / `metadata_machine.py` 的 `run()`(3 Agent 注册元组 `name + agent_type + preflight` 不变)

### 算法(纯精确匹配 + 轻量归一化,零 LLM)
- **author**:`author` / `last_saved_by` / `company` 三字段 NFKC 归一化后跨投标人精确聚类碰撞
- **time**:`doc_modified_at` 5 分钟滑窗聚集 + `doc_created_at` 跨文档精确相等
- **machine**:`app_name + app_version + template` 三字段元组精确碰撞

### 兜底(execution-plan §3 C10 原文)
- 元数据全缺失 → Agent 级 skip(`score=0.0` + `evidence.participating_fields=[]` 哨兵,对齐 C9)
- 单字段缺失 → 子维度 skip 不算 0(避免假阳)
- 3 子全 skip → Agent 整体 skip
- 子检测 flag 关闭 → 不进 scorer 归一化(Scenario 5)

### 配置(env,统一 `METADATA_` 前缀)
- `METADATA_AUTHOR_ENABLED` / `METADATA_TIME_ENABLED` / `METADATA_MACHINE_ENABLED`(默认 true)
- `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 5)
- `METADATA_AUTHOR_SUBDIM_WEIGHTS`(author 子维度内 author/last_saved_by/company 三字段权重,默认 `0.5,0.3,0.2`)
- `METADATA_MAX_BIDDERS_PER_PROJECT`(保护阈值,默认 200)

## Capabilities

### New Capabilities
<!-- 无新 capability -->

### Modified Capabilities

- `detect-framework`:3 个 metadata Agent 从 dummy 列表移除;新增 5 Req(extractor 共享数据源 / 3 子维度算法契约 / preflight 要求 / scorer 合成规则 / flag 配置)
- `parser-pipeline`:文档元数据提取扩 `Template` 字段;新增 2 Req(`document_metadata.template` 数据契约 / 回填脚本)

## Impact

### 受影响代码
- `backend/app/models/document_metadata.py`(加 `template` 列)
- `backend/app/services/parser/content/__init__.py`(Template 字段提取 + 写入)
- `backend/app/services/detect/agents/metadata_{author,time,machine}.py`(dummy → 真实算法)
- 新增 `backend/app/services/detect/agents/metadata_impl/` 子包(9 文件)
- 新增 `backend/scripts/backfill_document_metadata_template.py`

### 受影响数据库
- alembic 0007:`document_metadata` 加 `template` 列(SQLite/PostgreSQL 双兼容)

### 受影响 spec
- `openspec/specs/detect-framework/spec.md`(+5 Req)
- `openspec/specs/parser-pipeline/spec.md`(+2 Req)

### 不受影响
- `detect/registry.py` / `engine.py` / `judge.py` / `context.py`(锁定不变)
- 10 Agent 注册元组(`name + agent_type + preflight`)不变
- `AgentRunResult` 契约不变
- 前端组件不变(judge 层聚合 evidence,前端按 C6 既有渲染)

### 依赖/包
- 零新增第三方依赖(NFKC 用 `unicodedata` 标准库)

### 部署
- 生产部署需跑 alembic 0007 迁移 + 手工跑 `backfill_document_metadata_template.py` 回填历史文档 template 字段

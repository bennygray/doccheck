## Why

C3 完成后,审查员可创建项目但项目内**没有任何投标人/文件**——项目详情页的 `bidders / files / progress` 三个占位 section 都是空的。C4 把投标人 CRUD、压缩包上传、安全解压、文件列表与解析状态、报价规则元配置一次性补齐,使审查员能完成"建项目 → 加投标人 → 上传文件 → 看到解压后文件树"的端到端流程。这是 M2 核心流程的最后一块,完成后系统从"骨架"进入"可输入数据"。

本次 propose 阶段已与用户敲定 4 项关键边界(详见 design.md):

- **A2**:整体做 C4(不拆 C4a/C4b),接受范围超载,Requirement 估 ~12 / Scenario 估 ~38
- **B1**:解压走 minimal `asyncio.create_task`,不引入 ProcessPoolExecutor(留 C6 升级)
- **C2**:报价规则 = 元配置完整做 + 列映射表骨架(LLM 调用留 C5)
- **D2**:加密包检测 + 标记 + 密码重试,不做"3 次冻结"(留 C17 顺手)

## What Changes

### 数据模型(3 张新表 + alembic 0003)

- **`bidders`**:`name (≤200) / project_id FK / parse_status (pending|extracting|extracted|partial|failed|needs_password) / file_count / identity_info JSONB / created_at / updated_at / deleted_at`
- **`bid_documents`**:`bidder_id FK / file_name / file_path / file_size / file_type / md5 / file_role (placeholder, 留 C5 LLM 填)/ parse_status / parse_error / source_archive / created_at`
- **`project_price_configs`**:1:1 关联 `projects`,`currency (CNY|USD|EUR|...) / tax_inclusive (bool) / unit_scale (yuan|wan_yuan|fen)`
- **`price_parsing_rules`** (骨架):`project_id FK / sheet_name / header_row / column_mapping JSONB / created_by_llm (bool) / confirmed (bool) / created_at`;C4 提供 GET/PUT 端点,数据由 C5 LLM 填

### 后端端点(11 个新)

- 投标人:`POST/GET /api/projects/{pid}/bidders`、`GET/DELETE /api/projects/{pid}/bidders/{bid}`
- 文件:`POST /api/projects/{pid}/bidders/{bid}/upload`(同时是 US-3.1 创建+上传 与 US-3.2 追加上传的入口)、`GET /api/projects/{pid}/bidders/{bid}/documents`、`DELETE /api/documents/{id}`、`GET /api/documents/{id}/download`
- 解密:`POST /api/documents/{id}/decrypt {password}`(D2 范围,无次数冻结)
- 报价规则:`GET/PUT /api/projects/{pid}/price-config`(元配置)、`GET/PUT /api/projects/{pid}/price-rules`(列映射骨架)

### 后端服务(2 个新模块)

- `app/services/upload/`:multipart 接收 + MD5 计算 + 落盘到 `uploads/<project_id>/<bidder_id>/`;魔数校验(防扩展名伪造);500MB 大小校验
- `app/services/extract/`:压缩包解压(zipfile / py7zr / rarfile)+ zip-bomb 防护(总大小 ≤2GB / 文件数 ≤1000 / 嵌套 ≤3)+ zip-slip 防护(路径 normalize + 拒绝 `..` / 绝对路径)+ GBK/UTF-8 编码自适应 + 加密包检测;`asyncio.create_task` 起后台任务,状态写 DB

### 前端(投标人卡片 + 上传弹窗 + 文件树 + 报价规则配置)

- `pages/projects/ProjectDetailPage.tsx`:替换 C3 留下的 `bidders-placeholder / files-placeholder` 两个 section,渲染真实投标人列表 + 文件树
- `components/projects/AddBidderDialog.tsx`:US-3.1 弹窗(投标人名输入 + 文件拖拽/选择)
- `components/projects/UploadButton.tsx`:US-3.2 追加上传按钮
- `components/projects/FileTree.tsx`:US-3.3 文件树展示 + 解析状态徽章
- `components/projects/DecryptDialog.tsx`:D2 加密包密码重试弹窗
- `components/projects/PriceConfigForm.tsx`:US-4.4 元配置表单(币种/含税/单位)
- `components/projects/PriceRulesPlaceholder.tsx`:US-4.4 列映射占位区(C4 阶段空态,提示"等待 LLM 识别后展示")
- `services/api.ts`:扩展 ~10 个 API 方法
- `types/index.ts`:扩展 Bidder / BidDocument / PriceConfig / PriceParsingRule 类型

### 文档联动

- 归档时更新 `docs/handoff.md` §1/§2/§5
- 不修订 user-stories(本次实现与 user-stories 描述一致;US-4.4 的列映射在 spec 内显式标注"骨架 only,LLM 在 C5")

## Capabilities

### New Capabilities

- `file-upload`:投标人 CRUD + 压缩包上传 + 安全解压 + 文件列表 + 加密包密码重试 + 报价规则元配置 + 报价列映射骨架

### Modified Capabilities

- `project-mgmt`:`ProjectDetailResponse` 的 `bidders / files / progress` 占位字段由 C4 实装(从 `[] / [] / null` 改为返回真实投标人摘要 + 文件计数 + 解析进度概览);需要在 spec 增加 MODIFIED Requirement 描述新返回结构

## Impact

- **受影响代码**
  - 后端新增:`models/{bidder,bid_document,price_config,price_parsing_rule}.py` + `schemas/{bidder,bid_document,price}.py` + `api/routes/{bidders,documents,price}.py` + `services/upload/` + `services/extract/` + `alembic/versions/0003_*.py`
  - 后端改造:`api/routes/projects.py`(详情端点扩字段);`tests/fixtures/auth_fixtures.py` 的 `clean_users` 按 FK 顺序加 `delete bid_documents → delete bidders` 两行
  - 前端新增:`pages/projects/ProjectDetailPage.tsx` 替换 + 6 个新组件 + types 扩展 + api 扩展
  - 测试:L1 后端 ~25 用例(模型/解压安全/魔数/编码)+ L1 前端 ~10 用例 + L2 后端 ~38 用例(对应 spec Scenario)+ L3 1 主线 + 1 加密包 spec
- **新依赖**(后端 pyproject.toml)
  - `py7zr>=0.21`(7z 支持)
  - `rarfile>=4.2`(RAR 支持,需系统装 unrar 二进制 → 写进 README;CI 装不上则 RAR 测试 skip)
  - `chardet>=5.2`(GBK/UTF-8 编码探测)
  - `python-magic>=0.4`(Windows 用 `python-magic-bin`;魔数校验,防扩展名伪造)
- **存储与运维**
  - 上传目录:`backend/uploads/<project_id>/<bidder_id>/<archive_name>`(原压缩包)
  - 解压目录:`backend/extracted/<project_id>/<bidder_id>/<archive_name_no_ext>/...`
  - `.gitignore` 加 `backend/uploads/` 与 `backend/extracted/`
  - 目录大小限制由 OS/磁盘配额管;C1 已建的数据生命周期 `lifecycle_task` 在 C4 不扩展(留下次)
- **不涉及**
  - 不实现"3 次密码错冻结"(D2 决策,留 C17)
  - 不实现 LLM 报价识别(C2 决策,列映射表只建骨架)
  - 不升级 ProcessPoolExecutor(B1 决策,留 C6)
  - 不实现断点续传(US-3.2 兜底"上传中断可续传"超出本期范围,前端只做"失败重试")
  - 不实现 SSE 解压进度推送(C1 已有 `/demo/sse` 骨架,但 C4 内进度走轮询 `GET documents` 拿 status,SSE 集成留 C6)
  - 不实现追加上传后"重新检测"提示(US-3.2 AC-7 跨越 C6 检测范围,留 C6)

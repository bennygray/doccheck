## Why

真实案例 `e2e/artifacts/supplier-ab/` 中两份 macOS Archive Utility 打包的投标 zip 暴露 3 个级联缺陷:上传后 parser 流水线静默降级为无意义结果(`bid_documents.role` 全 None、`bidders.identity_info` 全 null、检测报告返回"全零 + 低风险"的误导结论),用户以为"流程跑不同/卡住了"。根因是我们把"跨平台打包场景"作为隐性假设而非显式规格,macOS 包的资源叉文件、UTF-8 无 flag 文件名、以及依赖文件名的 role 分类链路都在同一个场景下级联崩塌。

## What Changes

- **新增** 压缩包入库前的"打包垃圾"静默过滤机制:`__MACOSX/` / `._*` / `.DS_Store` / `Thumbs.db` / `desktop.ini` / `~$*` / `.~*` / `.git/` 等系统/编辑器/Office 锁文件不产生 `bid_documents` 行
- **修改** ZIP 文件名解码策略:在当前"UTF-8 flag → GBK 启发式 → chardet"链路之前插入"UTF-8 字节模式合法性检查"层,macOS 打包的 UTF-8 无 flag 文件名正确解码而不再被误判为 GBK
- **修改** role 分类降级逻辑:LLM 调用失败后的关键词兜底,在"文件名关键词"前增加"首段正文关键词"一层,文件名异常时仍能分配 role
- **非范围**(另开 change):ProcessPool 崩溃隔离、judge LLM 的"全零即低风险"误导性结论、identity_info 缺失时的 UI/报告降级文案

## Capabilities

### New Capabilities

（无;三个子问题都落在现有 capability 上）

### Modified Capabilities

- `file-upload`:新增"打包垃圾静默过滤"Requirement + "ZIP 文件名 UTF-8 优先解码"Requirement(后者修订当前仅"UTF-8 flag + GBK 默认"的解码策略)
- `parser-pipeline`:修订"LLM 角色分类降级策略"Requirement,增加内容关键词兜底层

## Impact

- **代码**:
  - 新增 `backend/app/services/extract/junk_filter.py`(纯函数模块)
  - 修改 `backend/app/services/extract/engine.py`(两处插入点:ZIP 路径 + 7z/rar 路径)
  - 修改 `backend/app/services/extract/encoding.py`(新增 `_looks_like_utf8` + 调整决策顺序)
  - 修改 `backend/app/services/parser/role_classifier.py`(降级链路新增内容兜底层)
- **数据**:行为变化(过滤后 `bid_documents` 不再产生"打包垃圾"占位行),但不需要 migration;对存量数据无追溯修复动作
- **依赖**:不引入新依赖
- **测试**:新增 3 个 L1 单测文件 + 1 个 L2 集成测试文件;复用 `e2e/artifacts/supplier-ab/` 真实 zip 做 manual 凭证
- **向后兼容**:过滤行为只影响新上传;历史已入库的"打包垃圾占位行"不回溯清理(list 接口前端可见但不影响检测,如需清理另走脚本)

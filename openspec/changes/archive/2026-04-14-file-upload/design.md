## Context

C3 已落地项目 CRUD 与权限隔离,前端 `ProjectDetailPage` 留有 `bidders-placeholder / files-placeholder / progress-placeholder` 三个占位 section。C2 已建 `get_current_user / require_role` 依赖、`User` 模型与 JWT 鉴权链。C1 已建 alembic 框架(head=`0002_projects`)、`AsyncSession` 配置、SSE 骨架、生命周期清理 dry-run。

C4 是 M2 第三个 change,完成后 M2 的"上传压缩包 → 自动解析 → 看到投标人+文件角色+报价"中的"上传 + 解压"环节落地(报价/角色识别由 C5 完成)。

C4 propose 阶段与用户敲定 4 项关键边界:

- **A2 整体做**:不拆 C4a/C4b,接受 ~12 Req / ~38 Scenario,超 spec 推荐阈值
- **B1 minimal asyncio.create_task**:解压走单进程协程,不引 ProcessPoolExecutor;丢任务风险写 follow-up
- **C2 元配置 + 列映射骨架**:报价规则元配置完整做,列映射只建表 + GET/PUT 端点骨架(LLM 调用留 C5)
- **D2 检测+标记+密码重试无冻结**:加密包检测 + 密码重试,3 次冻结留 C17

## Goals / Non-Goals

**Goals:**

- 审查员可在项目详情页添加投标人(US-3.1)、追加上传(US-3.2)、查看文件树+解析状态(US-3.3)、删除投标人(US-3.4)
- 系统能安全解压 ZIP/7Z/RAR(US-4.1):防 zip-bomb / zip-slip / 嵌套 / 加密包;GBK 中文文件名能还原
- 上传请求快速返回 201(<1s),解压在后台异步进行;前端轮询 `GET documents` 拿 `parse_status`
- 加密包检测 → 标 `needs_password` → 用户输密码 → 重新解压成功
- 项目级"币种 / 含税 / 单位"元配置可 CRUD,在项目详情页表单回显
- 列映射表(`PriceParsingRule`)与端点骨架就位,C5 LLM 直接灌数

**Non-Goals:**

- **不实现 LLM 报价表识别**(C5 范围)
- **不实现 LLM 文档角色分类**(C5 范围;C4 内 `bid_documents.file_role` 字段建好但保持 NULL)
- **不实现 ProcessPoolExecutor**(B1 决策,asyncio.create_task 单进程协程足够 demo)
- **不实现"密码错 3 次冻结"**(D2 决策,留 C17)
- **不实现断点续传**(US-3.2 兜底"上传中断可续传",超期推到第二期)
- **不实现 SSE 解压进度推送**(轮询足够;SSE 集成留 C6)
- **不实现追加上传后"重新检测"提示**(检测在 C6+)
- **不实现 PriceParsingRule 的 LLM 写入路径**(只建 GET/PUT 端点,L2 用 fixture 直接 INSERT 测 round-trip)
- **不实现 DOC/XLS/PDF 文件解析**(US-3.3 AC-5 明确"标记跳过");C4 内 `parse_status='skipped'` + `parse_error='暂不支持 X 格式'`

## Decisions

### D1. 投标人删除 = 软删 + 文件硬删

**选择**:`bidders.deleted_at` 软删(与 C3 项目软删一致);但**关联文件目录与 DB 记录**在删除时**同步硬删**(`bid_documents` DELETE + `extracted/<project_id>/<bidder_id>/` rmtree)。

**理由**:

- 项目软删后文件物理保留 → 由生命周期任务清(C3 决策)。但**投标人级别**的删除是审查员主动纠错(US-3.4 描述"修正项目数据"),物理保留没意义,反而占盘
- 软删 `bidders` 主表是为了审计("谁在何时删了哪个投标人"),`identity_info` JSONB 保留可追溯
- 文件硬删:解压产物可重新从原压缩包再解压一次(原压缩包仍在 `uploads/`),所以"重要文件"留在 `uploads/` 目录,`extracted/` 是可重建的衍生物。生命周期任务在投标人软删后清理 `uploads/`(留下次扩展)

**替代方案**:

- 统一硬删(投标人+文件+目录) — 拒绝,失去审计
- 统一软删(连解压目录都保留) — 拒绝,disk 占用增长不可控
- 文件标记 deleted_at 但物理保留 — 拒绝,N×500MB 无意义

### D2. 上传端点 = 单一 `POST /upload`,接受 multipart;无文件也允许(创建空投标人)

**选择**:`POST /api/projects/{pid}/bidders` 接受 multipart form,字段 `name` 必填、`file` 选填。

- `name` 提供、无 `file`:创建投标人 `parse_status=pending`,不落盘
- `name` 提供、有 `file`:创建投标人 + 落盘 + `asyncio.create_task` 起解压 + 立即返 201
- 已有投标人追加上传 = `POST /api/projects/{pid}/bidders/{bid}/upload`,只接 `file`

**替代方案**:

- 拆 JSON 创建端点 + 单独上传端点 — 拒绝,违反 US-3.1 "一步完成"原则
- multipart + 多文件一次传 — 推迟,US-3.1 描述只允许单文件,多文件场景留追加上传

### D3. 文件存储路径 = `uploads/<pid>/<bid>/` + `extracted/<pid>/<bid>/<archive_name>/`

**选择**:

- 原压缩包:`backend/uploads/<project_id>/<bidder_id>/<sha256前16>_<original_name>`(用 hash 前缀防同名冲突,保留原名提示用户)
- 解压产物:`backend/extracted/<project_id>/<bidder_id>/<sha256前16>_<original_name>/...`(原结构保留,zip-slip 防护后)

**替代方案**:

- UUID 命名 — 拒绝,user-stories US-3.3 AC-6 要求"下载原始文件",原文件名信息有用
- 全部走 S3 — 拒绝,本期单机部署,本地磁盘足够
- 目录用项目/投标人 name(非 id) — 拒绝,name 可改/含特殊字符,id 是稳定 PK

### D4. zip-bomb / zip-slip 防护 = 解压前 + 解压中双重校验

**zip-bomb 防护**(参考 US-4.1):

- 解压前:读取压缩包 metadata 总声明大小,>2GB 直接拒绝
- 解压中:实时累加已写入字节,超 2GB 中断 + 标 `failed`
- 解压前:压缩包内文件数 >1000 直接拒绝
- 嵌套深度:递归解压时计数,>3 层中断该子包

**zip-slip 防护**:

- 每个 entry 路径用 `os.path.normpath` + `os.path.realpath` 算出最终目标
- 检查最终目标是否在解压根目录下(`os.path.commonpath`);不在 → 跳过该 entry + 记 warning + 继续解压其余文件
- 不接受绝对路径(/ 或 C:\ 开头)
- 不接受路径含 `..` 段(在 normpath 后再检查)

**理由**:双重校验比单 metadata 检查更安全(metadata 可被篡改假报小尺寸,实际解压才知道真实);跳过单条恶意 entry 比"整包拒收"用户体验好(其他正常文件还能用)。

**替代方案**:

- 用 `safe_extract` 类库(zipfile-deflate64 等)— 评估后未选,Python 生态没有"统一"的 safe_extract,自己写防护逻辑可控且可单测

### D5. 加密包检测时机 = 解压时,而非上传时

**选择**:上传时不检测加密(因为 7z/rar 加密包检测需要尝试读 entry header,本质上是开始解压);解压协程开始后第一个动作就是 try-read,捕获 `RuntimeError`("Bad password") / `BadZipFile` / py7zr 的 `PasswordRequired` → 标 `needs_password` 并退出协程。

**密码重试流程**:

```
POST /api/documents/{id}/decrypt {password: "xxx"}
→ 状态校验:必须 needs_password,否则 409
→ asyncio.create_task 起新解压,带 password 参数
→ 立即返 202(已重新触发)
前端继续轮询 status
- 解压成功 → status=extracted
- 密码错误 → status=needs_password,parse_error="密码错误"(D2 不计数)
```

**替代方案**:

- 上传时同步检测加密 — 拒绝,需要先把文件落盘才能检测,且 7z/rar 检测本质上是"尝试解压第一个 entry",会引入双倍 IO

### D6. 异步解压实现 = `asyncio.create_task` + DB 状态机

**选择**:

```python
async def extract_archive(bidder_id: int, password: str | None = None) -> None:
    # 自己开 session,不复用请求级 session
    async with async_session() as session:
        # 改 status=extracting → 解压 → 写 bid_documents → 改 status=extracted/failed/needs_password
        ...

# 在路由内:
asyncio.create_task(extract_archive(bidder_id))
return 201  # 立即返回
```

**关键细节**:

- 协程内**自己开 session**(不复用请求级,避免 session lifecycle 与 task 生命周期绑死)
- 协程内任何异常都 catch 并写入 `bidders.parse_status='failed'` + `parse_error`,绝不让协程死掉时无人收尸
- 不使用 `BackgroundTasks`(FastAPI 内置):它的 session 自动关闭机制会卡到协程内
- 测试模式可通过 `INFRA_DISABLE_EXTRACT=1` 跳过自动起协程,L2 测试手动调 `extract_archive`

**已知风险**:

- event loop 重启 → 进行中任务丢失。bidder 永远卡在 `extracting`。**Mitigation**(留 follow-up):C6 任务表上线后,启动时扫描"卡住"状态恢复
- 单进程并发 → 多个 500MB 压缩包同时解压会让协程之间互相饿死(I/O bound 不致命,CPU bound 会)。**接受**:C4 阶段单用户 demo 不构成压力;C6 升级 ProcessPoolExecutor 解决

### D7. 文件类型校验 = 魔数 + 扩展名双校验

**选择**:用 `python-magic`(libmagic 绑定)读文件首 N 字节判断真实类型,与扩展名比对,任一不匹配拒绝(415)。

**白名单**:

- 压缩包:zip / 7z / rar(magic + 扩展名都要在列表内)
- 解压后单文件:docx / xlsx / jpg / png / bmp / tiff(其他标 skipped 入库,不删)

**Windows 装包**:`python-magic-bin`(自带 libmagic);Linux 默认装 libmagic;CI/Docker 镜像装 `apt-get install libmagic1`

**替代方案**:

- 仅扩展名校验 — 拒绝,US-3.2 AC-8 明确要求魔数防伪造
- `filetype` 库(纯 Python,无 C 依赖)— 评估后未选,识别率低于 libmagic,且不支持自定义规则

### D8. MD5 去重粒度 = 投标人内,而非项目内 / 全局

**选择**:`bid_documents.md5` 加单 bidder 内的 unique constraint(`UNIQUE(bidder_id, md5)`)。同 bidder 追加上传重复文件 → 跳过 + 返回 `skipped_duplicates: [...]` 列表;**不同 bidder 上传相同文件不算重复**。

**理由**:

- 不同投标人交相同文件**本身就是围标信号**(C7 文本相似度会命中);不能在上传层去重把信号过滤掉
- 同一 bidder 重复上传往往是用户误操作,跳过即可
- 全局 MD5 去重(共享存储)是 phase-2 优化,与本期解耦

### D9. 报价规则 = 一对一 + 一对多 两张表

**选择**:

- `project_price_configs`:与 `projects` **一对一**(项目 ID 同时作 PK + FK);项目创建时**不**自动 INSERT 默认配置,首次访问 `GET /price-config` 时返 `null`,前端引导用户配置
- `price_parsing_rules`:与 `projects` **一对多**(一个项目可能有多个 sheet 各自一套规则);C4 阶段表是空的,GET 返 `[]`,LLM(C5)填充

**列映射 JSONB schema**(为 C5 LLM 输出预定义):

```json
{
  "code_col": "A",          // 项目编码列
  "name_col": "B",          // 项目名称列
  "unit_col": "C",          // 单位列
  "qty_col": "D",           // 数量列
  "unit_price_col": "E",    // 单价列
  "total_price_col": "F",   // 合价列
  "skip_cols": ["G", "H"]   // 跳过列
}
```

PUT `/price-rules` 端点接受这个结构,L2 测试用 fixture 直接构造 JSONB INSERT 验证 round-trip。

### D10. 前端拖拽 vs 文件选择 = 同一组件双入口

**选择**:`AddBidderDialog` 内的文件输入区同时支持:

- 原生 `<input type="file" hidden>` + label 触发(键盘可达 + screen reader 友好)
- HTML5 drag-drop(`onDragOver / onDrop`)
- 选择/拖拽走同一个 onChange 处理

**Playwright L3 测试只覆盖原生 file input 路径**(`page.setInputFiles`),拖拽路径标 manual(L3 测拖拽很 flaky,C2 / C3 时也未碰)。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| `asyncio.create_task` 协程异常无人收尸 → 投标人卡 `extracting` | 协程顶层 try/except 全捕获,异常分支必须写 DB(`failed` + `parse_error`);L2 单测覆盖"解压抛异常应正确写 status" |
| event loop 重启丢任务 → 卡 `extracting` 永久 | 已知接受,follow-up 留 C6;C4 内提供 admin 接口 `POST /api/admin/bidders/{id}/reset-extract`(范围内不做)— 改为 follow-up 文档 |
| 大压缩包解压时间长(500MB / 5min)→ 用户以为卡了 | 前端轮询 `GET documents` 间隔 2s,显示"解析中..."加进度估计("已解析 X 个文件");无真实 % 进度(异步框架升级前难做) |
| zip-slip 防护漏洞 → 路径穿越 | normpath + realpath + commonpath 三道;**单测必须覆盖**:`../etc/passwd` / `..\windows\system32` / 绝对路径 / 符号链接 entry |
| GBK 中文文件名乱码 → 用户文件丢失 | `chardet` 自动探测 + ZIP 标准的 UTF-8 flag 优先;探测失败默认 GBK(中国场景多数);乱码文件**不丢弃**,以乱码名落盘并标 warning |
| `python-magic` 在 Windows CI 装失败 | pin `python-magic-bin>=0.4` 并在 README 标明;Linux 用 `python-magic` 即可 |
| `rarfile` 需要系统 `unrar` 二进制 → CI/Docker 缺 | RAR 格式测试用 `pytest.mark.skipif(not shutil.which('unrar'))` 跳过;README 提示;主流是 ZIP/7Z |
| 加密 7z/rar 检测形态各异(库 API 不一致) | extract service 内部 try/except 三种典型异常(`RuntimeError("Bad password")` / `BadZipFile` / `PasswordRequired`)→ 统一映射到 `needs_password` |
| 文件大小 500MB 校验时机 | 双校验:multipart 入口前由 nginx/uvicorn 限(部署时配,本期 README 写明);uvicorn `MAX_REQUEST_SIZE` env;Python 侧再算实际写入字节数 |
| 上传/解压并发产生孤儿目录 | 解压协程使用 `try/finally` 清理临时目录;若解压失败,`extracted/.../<archive>/` 整目录 rmtree 回滚 |
| `ProjectDetailResponse` 改返回结构 = 与 C3 spec 的"占位字段恒为 [] / null"冲突 | 在 spec delta 加 `## MODIFIED Requirements` 显式覆盖 C3 的"为 C4+ 预留的占位字段" Req,保留 history 可追溯 |

## Migration Plan

1. `alembic revision -m "bidders documents price_config price_rules" --rev-id 0003_files`
2. 4 张表 + 3 个索引(`bidders.project_id` / `bid_documents.bidder_id` / `bid_documents.md5 unique 内 bidder`)
3. `alembic upgrade head` 双向验证
4. 部署 checklist 写入 README:
   - 创建 `backend/uploads` / `backend/extracted` 目录(boot 时自动创建)
   - 装 libmagic(Linux)或 python-magic-bin(Windows 已在 pyproject)
   - 装 unrar(可选,RAR 支持)
5. C4 归档时迁移随 commit 进入主干

**回滚策略**:`alembic downgrade 0002_projects` → 4 张新表 DROP;`uploads/` 与 `extracted/` 目录手动清。**风险**:已上传文件元数据丢失,但物理文件保留可恢复(用户重传)。C5+ 上线前回滚安全。

## Open Questions

无。propose 阶段 4 个决策点 A2/B1/C2/D2 已敲定;D1~D10 实现细节为我方判断,apply 时如发现冲突就地解决并写入 handoff 决策段。

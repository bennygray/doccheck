# Backend

围标检测系统后端 — Python 3.12 + FastAPI + SQLAlchemy(async)+ PostgreSQL。

## 依赖准备

```bash
cd backend
uv sync               # 装运行时依赖
uv sync --extra dev   # 加测试 / lint 工具
```

### C4 file-upload 系统依赖

C4 引入了压缩包解压链路,对宿主系统有额外要求:

- **libmagic**(`python-magic` 后端,做扩展名+魔数双校验)
  - Windows:`pyproject.toml` 已 pin `python-magic-bin`,自带 libmagic,无需手动装
  - Linux:`apt-get install libmagic1`
  - macOS:`brew install libmagic`
- **unrar**(`rarfile` 解 RAR 用;可选,缺失时 RAR 测试自动 skip)
  - Linux:`apt-get install unrar`
  - macOS:`brew install rar`
  - Windows:从 https://www.rarlab.com/ 下载 unrar.exe 并放到 PATH
- 7Z / ZIP 由 `py7zr` / 标准库 `zipfile` 直接处理,无系统依赖

### 运行时目录

服务首次写文件时自动创建以下目录,生产/容器部署需保证写权限:

- `backend/uploads/<project_id>/<bidder_id>/` — 投标人原压缩包
- `backend/extracted/<project_id>/<bidder_id>/<archive_hash>/` — 解压产物

两个目录都已加入 `.gitignore`。

### C5 parser-pipeline 依赖

C5 引入文档内容提取 + LLM 解析:

- **python-docx / openpyxl / Pillow / imagehash / lxml**:已在 `pyproject.toml`,`uv sync` 自动装
  - Pillow 在 Linux 可能需要 `apt-get install libjpeg-dev` 才能解 JPG 图片
- **LLM Provider**:通过环境变量配置(`app/services/llm/factory.py`):
  - `LLM_PROVIDER=openai` (默认) / `dashscope` / 其他 OpenAI-compat
  - `LLM_API_KEY=<key>`(必填,生产部署)
  - `LLM_BASE_URL=<url>`(可选,覆盖默认 base url)
  - `LLM_MODEL=<model name>`(默认 gpt-4o-mini,按 provider 调整)
  - `LLM_TIMEOUT_S=30`(默认 30s)
- **SSE 反代配置**(`/api/projects/{pid}/parse-progress`):
  ```nginx
  proxy_read_timeout 60s;       # >= heartbeat 间隔(15s)+ 余量
  proxy_buffering off;          # 与响应头 X-Accel-Buffering: no 配合
  ```

### C5 运行时环境变量

- `INFRA_DISABLE_PIPELINE=1`:禁用 pipeline 自动触发(L2 测试用,手动 await run_pipeline)
- `SSE_HEARTBEAT_INTERVAL_S=15`:SSE 心跳间隔(测试可缩短到 0.2)

### 部署 — 上传大小限制

`POST /api/projects/{pid}/bidders/` 与 `POST /api/projects/{pid}/bidders/{bid}/upload` 接受 ≤500MB multipart;反向代理需放开同等上限,否则 413 提前在反代层就会被拦下:

```nginx
client_max_body_size 500M;
```

uvicorn 自身没有 multipart 大小限制,但生产建议挂 nginx/Caddy 做边界防护。

### C6 detect-framework 依赖

C6 引入异步检测框架 + 10 Agent 骨架 + SSE 检测推送 + 通用任务表:

- **无新系统 / 第三方依赖**:纯 asyncio + SQLAlchemy + 复用 C5 progress_broker
- **启动时扫描 stuck 任务**:FastAPI lifespan startup 调 `scanner.scan_and_recover()`,心跳过期的 `async_tasks` 行会触发回滚 handler(extract / content_parse / llm_classify / agent_run 4 subtype)
- **ProcessPoolExecutor 接口预留**:`app/services/detect/engine.get_cpu_executor()`,C6 dummy Agent 不消费,C7+ 真 CPU Agent 调用
- **SSE 端点**:`/api/projects/{pid}/analysis/events`;nginx 同 C5 `proxy_read_timeout ≥ 60s` + `proxy_buffering off`

环境变量:

- `AGENT_TIMEOUT_S`(默认 300)— 单 Agent 超时秒数
- `GLOBAL_TIMEOUT_S`(默认 1800)— 整轮检测全局超时秒数
- `ASYNC_TASK_HEARTBEAT_S`(默认 30)— 心跳更新间隔
- `ASYNC_TASK_STUCK_THRESHOLD_S`(默认 60)— scanner 判 stuck 阈值
- `ASYNC_TASK_MAX_SCAN_ROWS`(默认 1000)— scanner 单次处理上限
- `INFRA_DISABLE_DETECT=1` — 测试用:`POST /analysis/start` 仅创建 AgentTask 行,不 asyncio.create_task 调度
- `INFRA_DISABLE_SCANNER=1` — 测试用:跳过 lifespan startup 的 scanner 扫描

### C7 detect-agent-text-similarity 依赖

C7 把 `text_similarity` Agent 的 `run()` 从 dummy 替换为真实双轨算法(本地 TF-IDF + LLM 定性),C8~C13 陆续替换其余 9 个 Agent。

- **零新增第三方依赖**:jieba / scikit-learn / numpy 均 C5 已引入
- **ProcessPoolExecutor 首个真消费者**:CPU 密集段(TF-IDF + cosine)走 `get_cpu_executor() + loop.run_in_executor()`;首个 pair 有 ~1s jieba + sklearn 子进程冷启动开销,后续复用 worker 无感知
- **LLM 调用**:按 requirements §10.8 L-4 prompt,LLM 失败(timeout / bad_json × 2)→ 降级为仅程序相似度,`evidence_json.degraded=true`,`AgentTask.status=succeeded`(降级非失败)
- **容器 cpu_count 验证**(C6 Q3 延伸):部署到容器后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`,若显著高于实际限额开独立 follow-up

环境变量(均可运行期调,文档级 C7 默认对小规模项目):

- `TEXT_SIM_MIN_DOC_CHARS`(默认 500)— 单侧选中文档总字符 < 此值 preflight 返 `skip "文档过短无法对比"`
- `TEXT_SIM_PAIR_SCORE_THRESHOLD`(默认 0.70)— 段落对 cosine 相似度 ≥ 此值才进 LLM 候选
- `TEXT_SIM_MAX_PAIRS_TO_LLM`(默认 30)— 单 pair 最多发 LLM 的段落对数(防 token 爆炸)

### C8 detect-agent-section-similarity 依赖

C8 把 `section_similarity` Agent 的 `run()` 从 dummy 替换为真实章节级双轨算法(正则切章 → 对齐 → 复用 C7 `text_sim_impl` 跑章节内 TF-IDF + LLM 定性);章节切分失败 → 降级到整文档粒度(A1 独立降级,与 C7 text_similarity 并行不耦合)。

- **零新增第三方依赖**:纯正则 + 复用 C7 `text_sim_impl/` 子包(只读,不改一字)
- **ProcessPoolExecutor 共享**:与 C7 共用同一 `get_cpu_executor()` 单例
- **LLM 调用**:章节对合并后按 `title_sim × avg_para_sim` 粗排,仅前 `TEXT_SIM_MAX_PAIRS_TO_LLM` 个发 LLM(复用 C7 上限,不叠加)

环境变量(C8 专属,与 C7 并列):

- `SECTION_SIM_MIN_CHAPTERS`(默认 3)— 任一侧章节数 < 此值触发降级到整文档粒度
- `SECTION_SIM_MIN_CHAPTER_CHARS`(默认 100)— 章节内字符 < 此值合并进前一章节
- `SECTION_SIM_TITLE_ALIGN_THRESHOLD`(默认 0.40)— title TF-IDF sim ≥ 此值算对齐成功(by title);否则走序号回退对齐

### C9 detect-agent-structure-similarity 依赖

C9 把 `structure_similarity` Agent 的 `run()` 从 dummy 替换为真实三维度结构相似度(纯程序化,不调 LLM):目录结构(docx 章节标题 LCS)/ 字段结构(xlsx 列头 + bitmask + 合并单元格 Jaccard)/ 表单填充模式(xlsx cell type pattern Jaccard)。维度级提取失败 → 该维度 skip,**不做 C8 式降级**;3 维度全失败 → PairComparison.score=0.0 + evidence.participating_dimensions=[] 作 "结构缺失" 哨兵。

同时延伸 C5 持久化:新增 `document_sheets` 表(`rows_json` + `merged_cells_json`)供 xlsx cell 级数据消费;C5 解析时双写 DocumentText + DocumentSheet;已有 xlsx 文档通过 `backend/scripts/backfill_document_sheets.py` 手工回填(幂等,错误隔离,`--dry-run` 预扫)。

- **零新增第三方依赖**:openpyxl(C5 已)+ SQLAlchemy JSONB(C3 已);LCS/Jaccard 手写
- **复用 C8 chapter_parser**:目录维度 import `section_sim_impl.chapter_parser.extract_chapters`(零改 C8)
- **ProcessPoolExecutor 共享**:目录 LCS 走 C7/C8 同一 `get_cpu_executor()`;字段/填充维度 Jaccard 同步不上 executor
- **alembic 迁移**:`0006_add_document_sheets`;部署后需手工 `uv run python -m scripts.backfill_document_sheets` 回填已有 xlsx

环境变量(C9 专属,与 C7/C8 并列):

- `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)— 目录维度:章节数 < 此值 → 该维度 skip
- `STRUCTURE_SIM_MIN_SHEET_ROWS`(默认 2)— 字段/填充维度:每 sheet 非空行 < 此值 → 该 sheet 不参与配对
- `STRUCTURE_SIM_WEIGHTS`(默认 `"0.4,0.3,0.3"`)— 三维度权重(目录/字段/填充),逗号分隔
- `STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`(默认 `"0.4,0.3,0.3"`)— 字段维度子权重(列头/bitmask/合并单元格)
- `STRUCTURE_SIM_MAX_ROWS_PER_SHEET`(默认 5000)— xlsx 持久化/消费时每 sheet 行数上限(超出截断 + warning)

回填脚本:

```bash
uv run python -m scripts.backfill_document_sheets            # 全量回填
uv run python -m scripts.backfill_document_sheets --dry-run  # 只扫不写
```

### C10 detect-agents-metadata 依赖

C10 把 3 个 metadata Agent(`metadata_author` / `metadata_time` / `metadata_machine`)的 `run()` 从 dummy 替换为真实算法(纯程序化,零 LLM):
- **author**:author / last_saved_by / company 三子字段 NFKC+casefold+strip 归一化后跨投标人精确聚类(hit_strength = `|∩| / min(|A|, |B|)`)
- **time**:`doc_modified_at` 5 分钟滑窗跨 bidder 聚集 + `doc_created_at` 秒级精确相等
- **machine**:`(app_name, app_version, template)` 三字段元组跨投标人精确碰撞

同时延伸 C5 持久化:`document_metadata` 表追加 `template VARCHAR(255) NULL` 列(alembic 0007);`parser/content/metadata_parser` 从 `docProps/app.xml` 读 `<Template>` 节点写入;已有文档通过 `backend/scripts/backfill_document_metadata_template.py` 手工回填。

- **零新增第三方依赖**:`unicodedata`(stdlib)+ `datetime` + `collections`
- **C6 contract 锁定**:3 Agent 注册 `name+agent_type+preflight` 三元组不变,仅替换 run()
- **alembic 迁移**:`0007_add_doc_meta_template`(revision 字符串受 alembic_version VARCHAR(32) 限制简写);部署后需手工 `uv run python -m scripts.backfill_document_metadata_template` 回填已有文档

环境变量(统一 `METADATA_` 前缀):

- `METADATA_AUTHOR_ENABLED` / `METADATA_TIME_ENABLED` / `METADATA_MACHINE_ENABLED`(默认 `true`)— 子检测 flag 单独开关
- `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 `5`)— 修改时间滑窗宽度(分钟)
- `METADATA_AUTHOR_SUBDIM_WEIGHTS`(默认 `"0.5,0.3,0.2"`)— 顺序 author,last_saved_by,company
- `METADATA_TIME_SUBDIM_WEIGHTS`(默认 `"0.7,0.3"`)— 顺序 modified_at_cluster,created_at_match
- `METADATA_IRONCLAD_THRESHOLD`(默认 `85.0`)— Agent score ≥ 阈值 → is_ironclad
- `METADATA_MAX_HITS_PER_AGENT`(默认 `50`)— evidence hits 截断上限

回填脚本:

```bash
uv run python -m scripts.backfill_document_metadata_template            # 全量回填
uv run python -m scripts.backfill_document_metadata_template --dry-run  # 只扫不写(显示前 5 样例)
```

### C11 detect-agent-price-consistency 依赖

C11 把 `price_consistency` Agent 的 `run()` 从 dummy 替换为真实算法(纯程序化,零 LLM,零新依赖),覆盖 4 子检测:

- **tail(尾数)**:跨投标人 `total_price` 的 `(尾 N 位字符串, 整数位长)` 组合 key 碰撞;组合 key 区分 ¥100 / ¥1100(尾 3 位都是 "100" 但整数位长 3 vs 4)
- **amount_pattern(金额模式)**:跨投标人 `(item_name 归一化, unit_price)` 对集合的精确匹配率;`>= threshold` 才计分
- **item_list(报价表项整体相似度)**:**两阶段对齐**——同模板(sheet 集合相同 + 同名 sheet 行数相同)→ 按 `(sheet_name, row_index)` 位置对齐"同项同价";否则按 `item_name` NFKC 归一精确匹配
- **series_relation(数列关系,Q5 第一性原理审新增)**:同模板对齐行序列,`B/A` 比值方差 < 阈值 → 等比命中 / `B-A` 差值变异系数 < 阈值 → 等差命中;**execution-plan §3 C11 原文未列**,本 change scope 扩展

口径策略(Q2 决策):**完全不读** `project_price_configs.currency` 与 `tax_inclusive` 字段,直接按 `PriceItem.total_price / unit_price` 原始数值比对;真"含税口径混用导致同价不同数值"的场景留 C14 LLM 综合研判处理。

数据源(Q4 决策):**只走 PriceItem 表**,不消费 `DocumentSheet`;结构信号归 C9 `structure_similarity` 专管。

- **零新增第三方依赖**:`unicodedata` + `decimal` + `statistics` + `collections` 全 stdlib
- **C6 contract 锁定**:`price_consistency` 注册 `name+agent_type+preflight` 三元组不变,仅替换 run();preflight 复用 C6 既有 `bidder_has_priced`
- **无 schema 变更 / 无回填脚本**:纯算法层 change

环境变量(统一 `PRICE_CONSISTENCY_` 前缀,共 13 条):

- `PRICE_CONSISTENCY_TAIL_ENABLED` / `PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED` / `PRICE_CONSISTENCY_ITEM_LIST_ENABLED` / `PRICE_CONSISTENCY_SERIES_ENABLED`(默认 `true`)— 4 子检测独立开关
- `PRICE_CONSISTENCY_TAIL_N`(默认 `3`)— 尾数位数
- `PRICE_CONSISTENCY_AMOUNT_PATTERN_THRESHOLD`(默认 `0.5`)— amount_pattern 命中阈值
- `PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD`(默认 `0.95`)— item_list 命中阈值
- `PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX`(默认 `0.001`)— 等比 ratios 方差上限
- `PRICE_CONSISTENCY_SERIES_DIFF_CV_MAX`(默认 `0.01`)— 等差 diffs 变异系数上限
- `PRICE_CONSISTENCY_SERIES_MIN_PAIRS`(默认 `3`)— series 子检测最低对齐样本
- `PRICE_CONSISTENCY_SUBDIM_WEIGHTS`(默认 `"0.25,0.25,0.3,0.2"`)— 顺序 tail,amount_pattern,item_list,series
- `PRICE_CONSISTENCY_IRONCLAD_THRESHOLD`(默认 `85.0`)— Agent score ≥ 阈值 → is_ironclad
- `PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER`(默认 `5000`)— 单 bidder PriceItem 加载上限
- `PRICE_CONSISTENCY_MAX_HITS_PER_SUBDIM`(默认 `20`)— 单子检测 evidence hits 截断

算法 version 标识:`evidence_json["algorithm"] == "price_consistency_v1"`(区分 dummy)。

### C12 detect-agent-price-anomaly 依赖

C12 新增垂直关系检测 Agent `price_anomaly`(global 型,第 11 Agent):单家 bidder 报价相对项目群体均值偏离检测,纯程序化(零 LLM)。registry 从 10 → 11(pair 7 + global 4)。

**产品级决策(propose 期)**:
- Q1:sample_size 下限 = **3 家**(贴 execution-plan §3 原文)
- Q2:标底路径本期**不支持**(evidence.baseline 保留 null 占位;follow-up C17 或独立 change)
- Q3:偏离方向 = **仅负偏离(low)**,阈值默认 **30%**(env 可覆盖)
- Q4:本期**纯程序化**,LLM 解释占位 null(evidence.llm_explanation 留 C14 回填)

**算法**:
- 样本过滤:INNER JOIN `bidders × price_items`,GROUP BY bidder SUM(total_price);软删 bidder 排除;无 price_items 的 bidder 自动过滤
- `mean = sum(total_price) / N`;`deviation = (total - mean) / mean`
- `direction='low'` + `deviation < -threshold` → outlier
- Agent 级 skip 哨兵:sample_size < min → `score=0.0 + participating_subdims=[] + skip_reason='sample_size_below_min'`
- 评分占位公式:`min(100, len(outliers)*30 + max(|deviation|)*100)`

环境变量(统一 `PRICE_ANOMALY_` 前缀,共 7 条):

- `PRICE_ANOMALY_ENABLED`(默认 `true`)— Agent 总开关
- `PRICE_ANOMALY_MIN_SAMPLE_SIZE`(默认 `3`)— 样本下限;关键参数,非法值抛 ValueError
- `PRICE_ANOMALY_DEVIATION_THRESHOLD`(默认 `0.30`)— 偏离阈值(0.30 = 30%);关键参数,非法值抛 ValueError
- `PRICE_ANOMALY_DIRECTION`(默认 `low`)— 偏离方向;本期仅实现 `low`,其他值运行期 fallback + warn
- `PRICE_ANOMALY_BASELINE_ENABLED`(默认 `false`)— 标底路径;本期硬 false,设 true 会 warn 但不改算法
- `PRICE_ANOMALY_MAX_BIDDERS`(默认 `50`)— 每项目最多处理 bidder 数
- `PRICE_ANOMALY_WEIGHT`(默认 `1.0`)— judge 合成权重占位(C14 可覆盖)

算法 version 标识:`evidence_json["algorithm"] == "price_anomaly_v1"`(区分 dummy)。

**DIMENSION_WEIGHTS 调整(judge.py)**:C12 新增 `price_anomaly: 0.07`;`price_consistency` 从 0.15 → 0.10;`image_reuse` 从 0.07 → 0.05;总和仍 = 1.00。

## C13 detect-agents-global 依赖

C13 替换剩余 3 个 global Agent 的 dummy run(),**归档后 11 Agent 全部为真实算法,dummy 列表清空**。

**决策(propose 期 Q1~Q5)**

- Q1 合并 1 个 change(`detect-agents-global`),3 子包并存不强行共用
- Q2 error_consistency 程序 + L-5 LLM 全落:铁证本期兑现(贴 spec §F-DA-02 + §L-5)
- Q3 image_reuse MD5 + pHash 双路(不引 L-7 LLM 非通用图,占位 follow-up)
- Q4 style 全 L-8 两阶段 LLM(贴 spec §F-DA-06 "LLM 独有,程序不参与")
- Q5 零新增依赖(`imagehash>=4.3` 已在 C5 引入)

**apply 现场决策**

- `_preflight_helpers.bidder_has_identity_info` 新增(同步,None / 非 dict / 空 dict 全返 False)
- error_consistency.preflight **任一 bidder 缺 → downgrade**(贴 spec + 既有 preflight test)
- 不扩 `AgentRunResult` NamedTuple:`has_iron_evidence` 从 OverallAnalysis.evidence_json 顶层读(judge.py +3 行支持 global 型铁证升级)
- style.run() 在 `len(all_bidders) < 2` 仍写 OA(skip_reason 前端可见)
- `imagehash.__sub__` 返 numpy int64 → 显式 `int(...)` cast 避免 JSONB 序列化失败
- `call_with_retry_and_parse`:JSON 解析失败也消费重试名额(贴 L-5 行为)

### error_consistency 算法

- **关键词抽取**:identity_info 4 类字段(company_name / short_name / key_persons / credentials)平铺 + 短词过滤 + NFKC 归一 + 去重
- **跨 bidder 交叉搜索**:双向在 `document_texts` body/header/footer/textbox/table_row 子串匹配,候选段落 ≤ `MAX_CANDIDATE_SEGMENTS`(RISK-19 防 token 爆炸)
- **L-5 LLM 深度判断**:按 pair 调用;返 `{is_cross_contamination, direct_evidence, confidence, evidence[]}`;JSON 解析容错 + 重试
- **铁证规则**:`direct_evidence=true AND is_cross_contamination=true AND !downgrade` → pair 铁证 → evidence 顶层 `has_iron_evidence=true` → judge 强制 total ≥ 85
- **LLM 失败兜底**:仅展示关键词命中 evidence,不铁证,标"AI 研判暂不可用"(RISK-20)
- 评分占位:`min(100, hit_count*20 + 40 if direct_evidence + confidence*20 if is_cross_contamination)`

**env(5 条,`ERROR_CONSISTENCY_` 前缀)**:`ENABLED` / `MAX_CANDIDATE_SEGMENTS`(严格 > 0)/ `MIN_KEYWORD_LEN`(严格 > 0)/ `LLM_TIMEOUT_S`(宽松)/ `LLM_MAX_RETRIES`(宽松)

### image_reuse 算法

- 小图过滤 + MD5 精确双路(优先) + pHash Hamming 双路(imagehash.hex_to_hash 比较)
- 同对图 MD5 命中后不进 pHash 路(去重);MAX_PAIRS 按 hit_strength 倒序截断
- 本期不升铁证:`evidence.llm_non_generic_judgment=null` 占位(L-7 LLM 留 follow-up)
- 评分占位:`min(100, md5_count * 30 + sum(phash_hit_strength) * 10)`

**env(5 条,`IMAGE_REUSE_` 前缀)**:`ENABLED` / `PHASH_DISTANCE_THRESHOLD`(严格 0~64)/ `MIN_WIDTH` / `MIN_HEIGHT`(严格 > 0)/ `MAX_PAIRS`(宽松)

### style 算法

- **L-8 两阶段全 LLM**(spec §F-DA-06 明文"LLM 独有,程序不参与"):Stage1 每 bidder 提风格特征 + Stage2 全局比对
- **抽样**:仅 `technical` 角色;TF-IDF IDF 过滤低 30% 高频通用段;100~300 字长度过滤;均匀抽 `SAMPLE_PER_BIDDER` 段
- **>20 bidder 自动分组**:`bidder_id` 升序每组 ≤ 20,组间不跨比(简化版,完整算法 follow-up)
- **局限性说明**:固定"风格一致可能源于同一主体操控,也可能源于委托同一代写服务"(spec §F-DA-06 强制)
- **Agent skip 哨兵**:Stage1 / Stage2 任一失败整维度 skip(不退化程序算法,spec 明确)
- 评分占位:`min(100, len(consistent_groups) * 30 + max(consistency_score) * 50)`

**env(6 条,`STYLE_` 前缀)**:`ENABLED` / `GROUP_THRESHOLD`(严格 >= 2)/ `SAMPLE_PER_BIDDER`(严格 5~10)/ `TFIDF_FILTER_RATIO`(宽松 0~1)/ `LLM_TIMEOUT_S`(宽松)/ `LLM_MAX_RETRIES`(宽松)

### LLM mock 入口(`tests/fixtures/llm_mock.py`)

单一入口,贴 CLAUDE.md "8 调用点共享":
- L-5:`make_l5_response` + `mock_llm_l5_iron / non_iron / no_contamination / failed / bad_json` 5 fixture
- L-8:`make_l8_stage1_response` + `make_l8_stage2_response` + `mock_llm_l8_full_success / stage1_failed / stage2_failed / bad_json_stage1` 4 fixture
- 测试用 `monkeypatch.setattr(error_impl.llm_judge, "call_l5", mock_...)` 注入

### 算法 version 标识

`evidence_json["algorithm_version"]` 区分 dummy:`error_consistency_v1` / `image_reuse_v1` / `style_v1`。

## C14 detect-llm-judge 依赖

L-9 LLM 综合研判(M3 收官):judge 占位加权公式升级为"公式 + LLM + clamp + 失败兜底"。`judge.compute_report` 纯函数契约不变。

### 5 env(`LLM_JUDGE_*` 命名空间)

| env | 类型 | default | 语义 |
|---|---|---|---|
| `LLM_JUDGE_ENABLED` | bool | `true` | L-9 总开关;`false` → 跳过 LLM 直接走降级模板 |
| `LLM_JUDGE_TIMEOUT_S` | int [1,300] | `30` | 单次 LLM 调用超时 |
| `LLM_JUDGE_MAX_RETRY` | int [0,5] | `2` | 失败重试次数(最多调用 `MAX_RETRY+1` 次) |
| `LLM_JUDGE_SUMMARY_TOP_K` | int [1,20] | `3` | 每维度 `top_k_examples` 截断 |
| `LLM_JUDGE_MODEL` | str | `""` | 留空 = 使用 LLM 客户端默认,非空值本期**不生效**(follow-up 接入 per-call model 切换) |

非法值全部 fallback default + warn log(宽松风格,贴 C11/C12)。

### 5 产品决策(Q1~Q5)

- **Q1 B**:预聚合结构化摘要喂 LLM(token 稳定 3~8k,不直喂 raw evidence_json)
- **Q2 A**:LLM 失败保留公式兜底(`total/level` 恒来自 `compute_report`,不 block 报告)
- **Q3 B**:LLM 只升不降,铁证硬下限 85 守护(clamp 严格 4 步)
- **Q4 C**:不做跨项目历史共现(显式登记 follow-up,独立 change;需先解 bidder identity 去重)
- **Q5 C**:降级态 `llm_conclusion` 前缀 `"AI 综合研判暂不可用"` + 公式结论模板(前端前缀 match 加 banner)

### clamp 规则(严格 4 步)

```
final = max(formula_total, llm_suggested_total)   # LLM 只能升
if has_ironclad: final = max(final, 85.0)         # 铁证硬下限
final = min(final, 100.0)                         # 天花板
level = compute_level(final)                      # ≥70 high / 40-69 medium / <40 low
```

### apply 现场 3 决策(design 未覆盖,apply 就地定)

1. **`AgentRunResult` 字段名以 `context.py` 为准**:是 `(score, summary, evidence_json)` 而非 design 里写的 `(dimension, score, evidence)`;`test_detect_registry.py::test_c14_agent_run_result_contract_unchanged` 按现值断言
2. **`e2e/conftest.py` autouse fixture `_disable_l9_llm_by_default`**:e2e 默认 patch `judge_llm.call_llm_judge` 返 `(None, None)` 走降级,避免既有 217 L2 触发真实 LLM 调用(成本/稳定性);C14 专属 e2e 显式 `monkeypatch.setattr` 覆盖
3. **fallback 前缀 `"AI 综合研判暂不可用"` 固定**:前端前缀 match 识别降级态加 banner;LLM prompt 显式约束"不得以此前缀开头",违反则视为失败重试

### LLM 调用契约(`judge_llm.call_llm_judge`)

- 输出 Schema:`{"suggested_total": float 0~100, "conclusion": str 非空, "reasoning": str 可选}`
- 失败判据(统一返 `(None, None)`,不部分接受):JSON 解析失败 / 缺字段 / `suggested_total` 超界 / `conclusion` 空串 / 冒犯前缀约束 / 超时
- 重试:消费一次 retry 名额;`MAX_RETRY+1` 次上限

### algorithm version

`llm_judge_v1`(首版简版 prompt;实战反馈后 N-shot examples / 输出格式精调留 follow-up)

## 常用命令

```bash
uvicorn app.main:app --reload                       # 启服务
alembic upgrade head                                # 迁移到最新
alembic downgrade -1                                # 回滚一档
pytest tests/unit/                                  # L1 单元
pytest tests/e2e/                                   # L2 接口 E2E
INFRA_DISABLE_LIFECYCLE=1 uvicorn ...               # 跳过生命周期清理(测试常用)
INFRA_DISABLE_EXTRACT=1 pytest ...                  # 跳过自动解压协程(L2 用 fixture 手动 await)
INFRA_DISABLE_PIPELINE=1 pytest ...                 # 跳过解析流水线协程(C5 L2 用 fixture 手动 await)
INFRA_DISABLE_DETECT=1 pytest ...                   # 跳过自动检测调度(C6 L2 用 fixture 手动 await)
```

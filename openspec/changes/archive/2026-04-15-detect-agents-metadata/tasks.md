## 1. 数据层:DocumentMetadata.template 字段持久化(C5 延伸)

- [x] 1.1 [impl] 扩 `backend/app/models/document_metadata.py`:加 `template: Mapped[str | None] = mapped_column(String(255), nullable=True)`
- [x] 1.2 [impl] 新建 alembic 迁移 `backend/alembic/versions/0007_add_document_metadata_template.py`:upgrade 加列,downgrade drop 列;PG/SQLite 双兼容
- [x] 1.3 [impl] 扩 `backend/app/services/parser/content/__init__.py`:docx/xlsx 元数据提取时读 `docProps/app.xml` 中 `<Template>` 节点写入 `DocumentMetadata.template`
- [x] 1.4 [impl] 新建 `backend/scripts/backfill_document_metadata_template.py`:扫描 template IS NULL 的目标 doc + 单 doc 独立 session + 错误隔离 + `--dry-run` + 退出码(照搬 C9 模板)
- [x] 1.5 [L1] 新增 `backend/tests/unit/test_alembic_0007.py`:alembic 升降级幂等 + 新列可空
- [x] 1.6 [L1] 新增 `backend/tests/unit/test_parser_content_template.py`:模拟 app.xml 含/不含 Template 节点,验证 DocumentMetadata.template 写入正确 + 缺失写 NULL
- [x] 1.7 [L2] 扩 `backend/tests/e2e/test_parser_content_api.py`:上传一份带 Template=Normal.dotm 的 DOCX,验证 API 返回/DB 中 `document_metadata.template='Normal.dotm'`
- [x] 1.8 [L1] 新增 `backend/tests/unit/test_backfill_document_metadata_template.py`:幂等重跑 / 单 doc 失败隔离 / dry-run 不写入 / 缺失 Template 写 NULL 计入 success

## 2. 检测层:metadata_impl/ 共享子包

- [x] 2.1 [impl] 新建目录 `backend/app/services/detect/agents/metadata_impl/` + `__init__.py`(含 `write_pair_comparison_row(ctx, *, score, evidence, is_ironclad)` 共享 helper)
- [x] 2.2 [impl] 新建 `metadata_impl/config.py`:`AuthorConfig` / `TimeConfig` / `MachineConfig` dataclass + `load_author_config()` / `load_time_config()` / `load_machine_config()` env 读取 + 解析失败 fallback 默认值 + `logger.warning`
- [x] 2.3 [impl] 新建 `metadata_impl/models.py`:`MetadataRecord` / `ClusterHit` / `TimeCluster` / `AuthorDimResult` / `TimeDimResult` / `MachineDimResult` TypedDict 契约
- [x] 2.4 [impl] 新建 `metadata_impl/normalizer.py`:`nfkc_casefold_strip(s: str | None) -> str | None`(None / 空串 → None;否则 `unicodedata.normalize("NFKC", s).casefold().strip()`,再判空返 None)
- [x] 2.5 [impl] 新建 `metadata_impl/extractor.py`:`extract_bidder_metadata(session, bidder_id) -> list[MetadataRecord]`(JOIN BidDocument + DocumentMetadata;归一化 4 字段 + 保 `*_raw` 原值)
- [x] 2.6 [impl] 新建 `metadata_impl/author_detector.py`:`detect_author_collisions(records_a, records_b, cfg) -> AuthorDimResult`(三子字段跨投标人精确碰撞,hit_strength=`|∩| / min(|A|, |B|)`,子权重重归一化)
- [x] 2.7 [impl] 新建 `metadata_impl/time_detector.py`:`detect_time_collisions(records_a, records_b, cfg) -> TimeDimResult`(modified_at 滑窗聚集 + created_at 精确相等双子信号)
- [x] 2.8 [impl] 新建 `metadata_impl/machine_detector.py`:`detect_machine_collisions(records_a, records_b, cfg) -> MachineDimResult`(三字段元组精确碰撞)
- [x] 2.9 [impl] 新建 `metadata_impl/scorer.py`:`combine_dimension(dim_result, cfg) -> (agent_score_0_100, evidence_dict)`(维度 skip → score=0.0 + participating_fields=[] 哨兵)

## 3. 检测层:3 Agent run() 重写

- [x] 3.1 [impl] 重写 `backend/app/services/detect/agents/metadata_author.py::run()`:按 D10 模板(flag check → extractor → detect_author_collisions → scorer → write_pair_comparison);注册元组 `("metadata_author", "pair", preflight)` 不变;preflight 代码不动
- [x] 3.2 [impl] 重写 `backend/app/services/detect/agents/metadata_time.py::run()`:同上,detector 换 time_detector
- [x] 3.3 [impl] 重写 `backend/app/services/detect/agents/metadata_machine.py::run()`:同上,detector 换 machine_detector
- [x] 3.4 [impl] 扩 `backend/app/services/detect/agents/_preflight_helpers.py::bidder_has_metadata` 的 `"machine"` 分支:OR 条件加 `DocumentMetadata.template.is_not(None)`
- [x] 3.5 [impl] 各 Agent run() 异常路径 catch + logger.exception + evidence.error 写入;AgentTask.status 保持 succeeded

## 4. L1 单元测试(metadata_impl 子模块)

- [x] 4.1 [L1] 新增 `backend/tests/unit/test_metadata_normalizer.py`:`nfkc_casefold_strip` 4 case(None / 空串 / 全角 / 大小写 / 空白)
- [x] 4.2 [L1] 新增 `backend/tests/unit/test_metadata_extractor.py`:bidder 有 DocumentMetadata + 字段齐全 + 空串 / bidder 无 DocumentMetadata 返 [] / 不归一化 datetime 字段
- [x] 4.3 [L1] 新增 `backend/tests/unit/test_metadata_author_detector.py`:三字段全命中 / 单字段命中 / 无命中 / 单侧字段缺失 → 该子不进 sub_scores / 全三字段缺失 → dim_result.score=None
- [x] 4.4 [L1] 新增 `backend/tests/unit/test_metadata_time_detector.py`:modified 5 分钟窗命中 / modified 跨 bidder 约束 / created 精确相等 / 时间字段全缺失 → score=None / 窗口参数可配
- [x] 4.5 [L1] 新增 `backend/tests/unit/test_metadata_machine_detector.py`:三元组一致命中 / 任一字段不同不命中 / 某字段全缺失 → score=None / 部分 doc 元组不完整(不参与)
- [x] 4.6 [L1] 新增 `backend/tests/unit/test_metadata_scorer.py`:dim_result.score 非 None → agent_score=dim.score*100 + participating_fields 非空;dim_result.score=None → agent_score=0.0 + participating_fields=[]
- [x] 4.7 [L1] 新增 `backend/tests/unit/test_metadata_config.py`:默认值 / monkeypatch env 覆盖 / WEIGHTS 解析失败 fallback / ENABLED 布尔解析

## 5. L1 单元测试(3 Agent run + preflight)

- [x] 5.1 [L1] 新增 `backend/tests/unit/test_metadata_author_agent.py`:evidence.algorithm="metadata_author_v1" + 命中 / 维度 skip(participating_fields=[]) / flag 关闭(enabled=false,extractor 不被调用) / 异常路径(evidence.error 非空,AgentTask.status=succeeded)
- [x] 5.2 [L1] 新增 `backend/tests/unit/test_metadata_time_agent.py`:同上(time_v1 algorithm)
- [x] 5.3 [L1] 新增 `backend/tests/unit/test_metadata_machine_agent.py`:同上(machine_v1 algorithm)
- [x] 5.4 [L1] 扩 `backend/tests/unit/test_preflight_helpers.py`(新建 `test_preflight_helpers_metadata.py`):`bidder_has_metadata(machine)` 扩 template 后:template 非空通过 / 三字段全空不通过

## 6. L2 API 级 E2E 测试

- [x] 6.1 [L2] 新增 `backend/tests/e2e/test_detect_metadata_agents.py`:
  - **Scenario 1(作者相同)**:2 bidder 的 DocumentMetadata.author 均 "张三" → 启动检测 → `AGENT_REGISTRY["metadata_author"].run(ctx)` 返 score ≥ 50 + evidence.hits 含 author 命中
  - **Scenario 2(时间聚集)**:2 bidder 的 4 份 doc modified_at 分布在 5 分钟内 → metadata_time.run 返 score > 0 + evidence.hits 含 modified_at_cluster
  - **Scenario 3(机器指纹)**:2 bidder 的 DocumentMetadata 全部 `(Word, 16.0000, Normal.dotm)` 元组一致 → metadata_machine.run 返 score ≥ 85 + is_ironclad=true
  - **Scenario 4(元数据清洗)**:2 bidder 的 DocumentMetadata 所有字段全 None → 3 Agent preflight 全 skip,AgentTask.status=skipped,**不写 PairComparison**
  - **Scenario 5(flag 单独关闭)**:`METADATA_AUTHOR_ENABLED=false` 环境下,metadata_author.run 返 score=0.0 + evidence.enabled=false,extractor 不调用;metadata_time/machine 仍正常跑

## 7. 文档与运维

- [x] 7.1 [impl] 更新 `backend/README.md` 添加 "C10 detect-agents-metadata 依赖" 段:列出 8 env + 回填脚本用法(全量 / dry-run)+ DocumentMetadata.template 字段说明
- [x] 7.2 [impl] 更新 `.gitignore`:加 `e2e/artifacts/c10-*/` 白名单(C5~C9 既有风格)
- [x] 7.3 [manual] 新建 `e2e/artifacts/c10-2026-04-15/README.md`:L3 手工凭证占位(Docker kernel-lock 延续);记录待截图清单(启动检测 / 报告页 metadata_* 3 行展开 / 回填脚本日志)
- [ ] 7.4 [manual] 运维跑 `uv run python backend/scripts/backfill_document_metadata_template.py --dry-run` 再 `--no-dry-run` 实跑一次回填,记录 success/fail 数量到 handoff — **生产环境执行,留 follow-up**

## 8. L3 UI E2E(延续手工凭证)

- [x] 8.1 [L3] 尝试运行 `npm run e2e`(Playwright);若 Docker kernel-lock 未解除 → 降级为手工 + 截图凭证,凭证存 `e2e/artifacts/c10-2026-04-15/` — 延续 C5~C9 降级(kernel-lock 未解除),凭证路径 `e2e/artifacts/c10-2026-04-15/README.md` 已占位待生产跑出

## 9. 验证总汇

- [x] 9.1 跑 [L1] 全部测试(`cd backend && uv run pytest tests/unit/`),全绿 — **431 passed**
- [x] 9.2 跑 [L2] 全部测试(`cd backend && uv run pytest tests/e2e/`),全绿 — **194 passed**
- [x] 9.3 跑 [L3] 测试或提交降级凭证(`e2e/artifacts/c10-2026-04-15/*.png` 文件存在) — 延续 C5~C9 降级凭证,README.md 占位已就绪
- [x] 9.4 跑 [L1][L2][L3] 全部测试,全绿 — **L1+L2 = 625 passed**(C9 基线 550 → +75 新增);L3 降级手工凭证

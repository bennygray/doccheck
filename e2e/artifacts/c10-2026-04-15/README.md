# C10 detect-agents-metadata L3 手工凭证占位

延续 C5~C9 降级策略:Docker Desktop kernel-lock 未解除。kernel-lock 解除后按下面步骤手工补 3 张截图。

## 前置

- 预埋 2 bidder × docx(`DocumentMetadata.author` 同为 "张三")→ Scenario 1
- 预埋 2 bidder × docx(`doc_modified_at` 在 5 分钟内)→ Scenario 2
- 预埋 2 bidder × docx(`app_name/app_version/template` 三字段元组完全相同)→ Scenario 3
- 另 1 bidder × docx(所有 metadata 字段全空,模拟清洗)→ Scenario 4
- 运行 `uv run python -m scripts.backfill_document_metadata_template --dry-run` 先确认目标数
- 运行 `uv run python -m scripts.backfill_document_metadata_template` 全量回填

## 3 张截图(保存为 01/02/03.png)

- **01-start-detect.png**:启动检测后,进度条显示 metadata_author / metadata_time / metadata_machine 三 Agent 同步运行;其中一个或多个命中铁证(is_ironclad=true)
- **02-report-metadata-rows.png**:报告页 3 个 metadata 维度行展开:
  - author 行 evidence.hits 含 field="author", value="张三" + doc_ids_a/b
  - time 行 evidence.hits 含 dimension="modified_at_cluster" + window_min=5 + times[]
  - machine 行 evidence.hits 含 field="machine_fingerprint" + value.{app_name, app_version, template}
- **03-backfill-log.png**:运维终端运行 `backfill_document_metadata_template.py` 的日志截图,含 `OK doc=N template='Normal.dotm'` 行 + 结尾 `total=N success=M failed=0`

## 通过判据

- evidence_json.algorithm ∈ {`metadata_author_v1`, `metadata_time_v1`, `metadata_machine_v1`}
- 作者相同命中:evidence.participating_fields 含 `author`,score 与子权重一致
- 时间聚集命中:evidence.sub_scores.modified_at_cluster > 0,hits 含 dimension="modified_at_cluster"
- 机器指纹命中:evidence.hits[0].field="machine_fingerprint" + value 三字段齐全,is_ironclad=true
- 元数据被清洗:3 Agent preflight 全 skip,PairComparison 表无 metadata_* 记录
- 子检测 flag 关闭(METADATA_AUTHOR_ENABLED=false):evidence.enabled=false,其他 2 Agent 正常

L1 431 + L2 194 = 625 通过,C10 新增 75 用例已覆盖所有 C10 spec scenario。L3 凭证仅作 M3 demo 价值补齐。

## 回填脚本手工验证

```bash
# 1. dry-run 查看目标数量
cd backend
uv run python -m scripts.backfill_document_metadata_template --dry-run
# 2. 实际回填
uv run python -m scripts.backfill_document_metadata_template
# 3. 幂等性验证 — 立即重跑应输出 total=0
uv run python -m scripts.backfill_document_metadata_template
```

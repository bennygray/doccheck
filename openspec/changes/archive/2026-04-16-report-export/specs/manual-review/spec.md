## ADDED Requirements

### Requirement: 整报告级人工复核

系统 SHALL 提供 `POST /api/projects/{project_id}/reports/{version}/review` 端点。body:`{status: 'confirmed'|'rejected'|'downgraded'|'upgraded', comment?: string}`。权限:reviewer 仅自己项目 / admin 任意。成功写入:
- `AR.manual_review_status = status`
- `AR.manual_review_comment = comment`
- `AR.reviewer_id = current_user.id`
- `AR.reviewed_at = NOW()`
- audit_log 记 `review.report_{status}`(target_type='report', target_id=AR.id;before_json={旧 status + comment};after_json={新 status + comment})

复核**不修改** `AR.total_score` / `AR.risk_level` / `AR.llm_conclusion`(D11)。

#### Scenario: 首次确认复核
- **WHEN** owner POST review `{status:'confirmed', comment:'证据充分'}`
- **THEN** 200;AR 4 字段写入;audit_log `review.report_confirmed` before={status:null, comment:null},after={status:'confirmed', comment:'证据充分'};检测原值不变

#### Scenario: 降级复核
- **WHEN** owner POST review `{status:'downgraded', comment:'时间戳重合系巧合'}`
- **THEN** AR.manual_review_status='downgraded';total_score 和 risk_level **不变**;audit_log `review.report_downgraded`

#### Scenario: 重复复核覆盖
- **WHEN** 已复核的报告再次 POST review
- **THEN** 200;AR 字段覆盖更新;audit_log before_json={旧 status + comment},after_json={新}

#### Scenario: 无权限复核返回 404
- **WHEN** reviewer A 复核 B 的项目报告
- **THEN** 404,不修改 AR,不写 audit_log

#### Scenario: 非法 status 返回 400
- **WHEN** status 不在枚举集 {'confirmed','rejected','downgraded','upgraded'}
- **THEN** 400,不修改 AR

---

### Requirement: 维度级人工复核(可选)

系统 SHALL 提供 `POST /api/projects/{project_id}/reports/{version}/dimensions/{dim_name}/review` 端点。body:`{action: 'confirmed'|'rejected'|'note', comment?: string}`。成功写入:
- `OverallAnalysis.manual_review_json = {action, comment, reviewer_id, at}`(该 project+version+dimension 行覆盖;若无 OA 行则 404)
- audit_log 记 `review.dimension_marked`,target_type='report_dimension',target_id=dim_name

维度级复核**不是必须**路径,可跳过直接做整报告级复核。

#### Scenario: 标记单维度
- **WHEN** owner POST dimension review `{action:'rejected', comment:'误判'}` 到 similarity 维度(该维度 OA 行存在)
- **THEN** 200;OA(dimension='similarity').manual_review_json 写入;audit_log `review.dimension_marked` target_id='similarity'

#### Scenario: 不存在的维度返回 404
- **WHEN** dim_name 不在 DIMENSION_WEIGHTS 枚举 或 该维度无 OA 行
- **THEN** 404

#### Scenario: 维度级复核不阻塞整报告复核
- **WHEN** 仅做了维度级复核未做整报告级 → 查询 AR
- **THEN** AR.manual_review_status 仍为 null(可后续补整报告级)

---

### Requirement: 复核不污染检测原始数据

所有复核操作 MUST 仅写入 `manual_review_*` 相关字段,**不得修改** `AR.total_score` / `AR.risk_level` / `AR.llm_conclusion` / `OA.score` / `OA.evidence_json` / `PC.*`。

#### Scenario: 复核后检测字段不变
- **WHEN** 对报告执行任意复核操作
- **THEN** AR.total_score 和 risk_level 的值与复核前完全相等(通过 before/after 对比验证)

#### Scenario: 导出文档同时展示检测原值和复核结论
- **WHEN** 导出已复核报告
- **THEN** Word 模板 review 段展示复核 status/comment;同时 report.total_score/risk_level 展示检测原值

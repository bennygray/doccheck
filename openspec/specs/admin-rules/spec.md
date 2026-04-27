## Purpose

定义 admin 角色管理检测规则(SystemConfig)的 API 与运行时契约,包括获取/更新/恢复默认配置、维度
权重与启用开关、检测引擎读取路径,以及前端 admin/rules 页交互。
## Requirements
### Requirement: Get rules config API
The system SHALL provide `GET /api/admin/rules` that returns the current SystemConfig JSON object containing: dimensions (12 entries with enabled/weight/llm_enabled and dimension-specific thresholds), risk_levels, doc_role_keywords, hardware_keywords, metadata_whitelist, min_paragraph_length, file_retention_days. Only admin role SHALL have access; reviewer calls SHALL receive 403. If no config exists in DB, the system SHALL return the built-in default config.

The 12 dimensions include the 10 originally shipped (with `price_ceiling` UI label updated to "异常低价偏离" — controls `price_anomaly` engine for low-price outlier detection) plus 2 newly added in this change: `price_total_match` (两家投标总额完全相等识别) and `price_overshoot` (任一投标超过最高限价识别). Both new dimensions trigger detection signals via `evidence["has_iron_evidence"]=True` short-circuit, NOT via SystemConfig weight; therefore they MAY have weight=0 in DEFAULT_RULES_CONFIG and still produce ironclad-level risk signals. This is intentional and SHALL be documented in design.md.

#### Scenario: Admin fetches rules
- **WHEN** admin calls `GET /api/admin/rules`
- **THEN** response is 200 with complete config JSON containing 12 dimension entries

#### Scenario: Reviewer denied access
- **WHEN** reviewer calls `GET /api/admin/rules`
- **THEN** response is 403

#### Scenario: No config in DB returns defaults
- **WHEN** system_configs table is empty and admin calls `GET /api/admin/rules`
- **THEN** response is 200 with built-in DEFAULT_RULES_CONFIG containing 12 dimensions; new 2 dimensions (`price_total_match`, `price_overshoot`) default weight=0

### Requirement: Update rules config API
The system SHALL provide `PUT /api/admin/rules` that accepts a complete config JSON object and overwrites the current config. Validation rules: dimension weights MUST be non-negative; risk_levels.high MUST be > risk_levels.medium > 0 and high ≤ 100; enabled/llm_enabled MUST be boolean; dimension-specific thresholds MUST be within valid ranges; metadata_whitelist MUST be a string array; file_retention_days MUST be > 0. Validation failure SHALL return 422. Only admin role SHALL have access.

#### Scenario: Valid config update
- **WHEN** admin calls `PUT /api/admin/rules` with valid config JSON
- **THEN** response is 200, subsequent GET returns updated config

#### Scenario: Negative weight rejected
- **WHEN** admin calls `PUT /api/admin/rules` with a dimension weight of -1
- **THEN** response is 422

#### Scenario: Discontinuous risk levels rejected
- **WHEN** admin calls `PUT /api/admin/rules` with risk_levels.high < risk_levels.medium
- **THEN** response is 422

#### Scenario: Threshold out of range rejected
- **WHEN** admin calls `PUT /api/admin/rules` with text_similarity threshold of 150
- **THEN** response is 422

### Requirement: Restore defaults
The system SHALL support restoring all rules to built-in defaults. When `PUT /api/admin/rules` receives `{restore_defaults: true}`, the system SHALL overwrite the config with DEFAULT_RULES_CONFIG. The "Restore Defaults" action SHALL be available from both the API and the frontend button.

#### Scenario: Restore defaults via API
- **WHEN** admin calls `PUT /api/admin/rules` with `{restore_defaults: true}`
- **THEN** response is 200, subsequent GET returns DEFAULT_RULES_CONFIG values

#### Scenario: Restore defaults via frontend
- **WHEN** admin clicks "Restore Defaults" button on rules page
- **THEN** all form fields reset to default values and config is saved

### Requirement: Detection engine reads SystemConfig
The detection engine SHALL read rules from SystemConfig before each detection run. Dimension weights from config SHALL override the hardcoded DIMENSION_WEIGHTS in judge.py. Dimension enabled=false SHALL cause that dimension to be skipped. Config values SHALL take precedence over env var defaults for agent thresholds. If SystemConfig is absent or a field is missing, the engine SHALL fall back to code defaults.

#### Scenario: Modified weight affects scoring
- **WHEN** admin sets text_similarity weight to 0.30 via PUT and triggers detection
- **THEN** the detection report uses 0.30 as text_similarity weight (not the hardcoded 0.12)

#### Scenario: Disabled dimension skipped
- **WHEN** admin sets image_reuse enabled=false and triggers detection
- **THEN** image_reuse agent is not executed, dimension score is absent from report

#### Scenario: Missing config falls back to defaults
- **WHEN** SystemConfig row is deleted and detection runs
- **THEN** engine uses hardcoded DIMENSION_WEIGHTS and env var defaults

### Requirement: Admin rules frontend page
The system SHALL provide an `/admin/rules` page accessible only to admin users. The page SHALL display a form with: 10 dimension groups (each with enabled checkbox, weight number input, llm_enabled checkbox, and dimension-specific threshold inputs), global config section (risk_levels, keyword textareas, whitelist textarea, min_paragraph_length, file_retention_days), a "Save" button, and a "Restore Defaults" button. Non-admin users navigating to `/admin/rules` SHALL be redirected to `/projects`.

#### Scenario: Admin views and edits rules
- **WHEN** admin navigates to `/admin/rules`
- **THEN** page displays form pre-filled with current config values

#### Scenario: Admin saves modified rules
- **WHEN** admin changes weight values and clicks "Save"
- **THEN** config is persisted, page reload shows saved values

#### Scenario: Non-admin redirected
- **WHEN** reviewer navigates to `/admin/rules`
- **THEN** redirected to `/projects`

### Requirement: SystemConfig database model
The system SHALL have a `system_configs` table with columns: id (Integer PK), config (JSON), updated_by (Integer FK to users.id, nullable), updated_at (DateTime). The table SHALL be initialized with a single row (id=1) containing DEFAULT_RULES_CONFIG on first application startup or via Alembic migration.

#### Scenario: Table initialized with defaults
- **WHEN** application starts with empty system_configs table
- **THEN** a row with id=1 and DEFAULT_RULES_CONFIG is inserted

#### Scenario: Config persists across restarts
- **WHEN** admin updates config and application restarts
- **THEN** GET /api/admin/rules returns the previously saved config


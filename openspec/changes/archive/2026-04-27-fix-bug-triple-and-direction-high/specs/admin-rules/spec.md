## MODIFIED Requirements

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

/**
 * 共享类型定义(C3 起建立)。
 *
 * 项目域类型对齐后端 `backend/app/schemas/project.py`。
 * bidder/file/progress 等 C4+ 类型暂不在此定义,等到对应 change 再补。
 */

export type ProjectStatus =
  | "draft"
  | "parsing"
  | "ready"
  | "analyzing"
  | "completed";

export type ProjectRiskLevel = "high" | "medium" | "low";

/** 项目基础字段(列表 + 创建都返这一套) */
export interface Project {
  id: number;
  name: string;
  bid_code: string | null;
  max_price: string | null; // Pydantic Decimal 序列化为字符串
  description: string | null;
  status: ProjectStatus | string;
  risk_level: ProjectRiskLevel | string | null;
  owner_id: number;
  created_at: string; // ISO 8601
  updated_at: string;
  deleted_at: string | null;
}

/** 列表项与基础字段同,保留别名以便未来分化(如列表返精简视图) */
export type ProjectListItem = Project;

// =============================================================================
// C4 file-upload 类型
// =============================================================================

export type ParseStatus =
  | "pending"
  | "extracting"
  | "extracted"
  | "skipped"
  | "partial"
  | "failed"
  | "needs_password"
  // C5 parser-pipeline 扩展(bidder 级 + 文档级部分共享)
  | "identifying"
  | "identified"
  | "identify_failed"
  | "pricing"
  | "priced"
  | "price_partial"
  | "price_failed";

/** C5: 9 种文档角色枚举(与后端 DocumentRole 对齐) */
export type DocumentRole =
  | "technical"
  | "construction"
  | "pricing"
  | "unit_price"
  | "bid_letter"
  | "qualification"
  | "company_intro"
  | "authorization"
  | "other";

/** C5: LLM 置信度 / 用户修正标记 */
export type RoleConfidence = "high" | "low" | "user";

export interface Bidder {
  id: number;
  name: string;
  project_id: number;
  parse_status: ParseStatus | string;
  parse_error: string | null;
  file_count: number;
  identity_info: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface BidderSummary {
  id: number;
  name: string;
  parse_status: ParseStatus | string;
  file_count: number;
}

export interface BidderListResponse {
  items: Bidder[];
  total: number;
}

export interface BidDocument {
  id: number;
  bidder_id: number;
  file_name: string;
  file_path: string;
  file_size: number;
  file_type: string;
  md5: string;
  file_role: DocumentRole | string | null;
  role_confidence: RoleConfidence | string | null;
  parse_status: ParseStatus | string;
  parse_error: string | null;
  source_archive: string;
  created_at: string;
}

export interface BidDocumentSummary {
  id: number;
  bidder_id: number;
  file_name: string;
  file_type: string;
  parse_status: ParseStatus | string;
  file_role?: DocumentRole | string | null;
  role_confidence?: RoleConfidence | string | null;
}

export interface ProjectProgress {
  total_bidders: number;
  pending_count: number;
  extracting_count: number;
  extracted_count: number;
  // C5 扩展
  identifying_count: number;
  identified_count: number;
  pricing_count: number;
  priced_count: number;
  partial_count: number;
  failed_count: number;
  needs_password_count: number;
}

export interface UploadResult {
  bidder_id: number;
  archive_filename: string | null;
  new_files: number[];
  skipped_duplicates: string[];
}

export type Currency = "CNY" | "USD" | "EUR" | "HKD";
export type UnitScale = "yuan" | "wan_yuan" | "fen";

export interface PriceConfig {
  project_id: number;
  currency: Currency | string;
  tax_inclusive: boolean;
  unit_scale: UnitScale | string;
  updated_at: string;
}

export interface PriceConfigPayload {
  currency: Currency | string;
  tax_inclusive: boolean;
  unit_scale: UnitScale | string;
}

export interface PriceParsingRule {
  id: number;
  project_id: number;
  sheet_name: string;
  header_row: number;
  column_mapping: Record<string, unknown>;
  created_by_llm: boolean;
  confirmed: boolean;
  created_at: string;
  updated_at: string;
}

export interface PriceParsingRulePayload {
  id?: number;
  sheet_name: string;
  header_row: number;
  column_mapping: Record<string, unknown>;
  created_by_llm?: boolean;
  confirmed?: boolean;
}

/** 详情返回(C4 起 bidders/files/progress 由后端真实聚合) */
export interface ProjectDetail extends Project {
  bidders: BidderSummary[];
  files: BidDocumentSummary[];
  progress: ProjectProgress | null;
}

export interface ProjectCreatePayload {
  name: string;
  bid_code?: string | null;
  max_price?: string | number | null;
  description?: string | null;
}

export interface ProjectListQuery {
  page?: number;
  size?: number;
  status?: ProjectStatus | string;
  risk_level?: ProjectRiskLevel | string;
  search?: string;
}

export interface ProjectListResponse {
  items: ProjectListItem[];
  total: number;
  page: number;
  size: number;
}

// =============================================================================
// C5 parser-pipeline 类型
// =============================================================================

/** C5 报价项返回(GET /price-items) */
export interface PriceItem {
  id: number;
  sheet_name: string;
  row_index: number;
  item_code: string | null;
  item_name: string | null;
  unit: string | null;
  quantity: string | null; // Decimal 序列化为字符串
  unit_price: string | null;
  total_price: string | null;
  created_at: string;
}

/** C5 SSE 事件类型(与后端 EventType 对齐) */
export type ParseProgressEventType =
  | "snapshot"
  | "bidder_status_changed"
  | "document_role_classified"
  | "project_price_rule_ready"
  | "bidder_price_filled"
  | "error"
  | "heartbeat";

export interface ParseProgressEvent {
  event_type: ParseProgressEventType;
  data: Record<string, unknown>;
}

/** PATCH /api/documents/{id}/role 响应 */
export interface DocumentRolePatchResult {
  id: number;
  file_role: DocumentRole | string;
  role_confidence: RoleConfidence | string;
  warn: string | null;
}

// =============================================================================
// C6 detect-framework 类型
// =============================================================================

/** AgentTask 6 态 */
export type AgentTaskStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "timeout"
  | "skipped";

export type AgentType = "pair" | "global";
export type RiskLevel = "high" | "medium" | "low";

export interface AgentTask {
  id: number;
  agent_name: string;
  agent_type: AgentType;
  pair_bidder_a_id: number | null;
  pair_bidder_b_id: number | null;
  status: AgentTaskStatus;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number | null;
  score: string | null; // Decimal 序列化为字符串
  summary: string | null;
  error: string | null;
}

/** POST /analysis/start 201 */
export interface AnalysisStartResponse {
  version: number;
  agent_task_count: number;
}

/** POST /analysis/start 409 */
export interface AnalysisStartConflict {
  current_version: number;
  started_at: string | null;
  message: string;
}

/** GET /analysis/status */
export interface AnalysisStatusResponse {
  version: number | null;
  project_status: string;
  started_at: string | null;
  agent_tasks: AgentTask[];
}

/** SSE 事件类型 */
export type DetectEventType =
  | "snapshot"
  | "agent_status"
  | "report_ready"
  | "heartbeat";

export interface DetectEvent {
  event_type: DetectEventType;
  data: Record<string, unknown>;
}

/** 项目详情的 analysis 字段 */
export interface ProjectAnalysisSummary {
  current_version: number | null;
  project_status: string;
  started_at: string | null;
  agent_task_count: number;
  latest_report: ProjectAnalysisReport | null;
}

export interface ProjectAnalysisReport {
  version: number;
  total_score: number;
  risk_level: RiskLevel;
  created_at: string;
}

/** GET /reports/{version} */
export interface ReportDimensionStatusCounts {
  succeeded: number;
  failed: number;
  timeout: number;
  skipped: number;
}

export interface ReportDimension {
  dimension: string;
  best_score: number;
  is_ironclad: boolean;
  status_counts: ReportDimensionStatusCounts;
  summaries: string[];
}

export interface ReportResponse {
  version: number;
  total_score: number;
  risk_level: RiskLevel;
  llm_conclusion: string;
  created_at: string;
  dimensions: ReportDimension[];
  // C15 新增:人工复核字段(未复核时 null)
  manual_review_status: "confirmed" | "rejected" | "downgraded" | "upgraded" | null;
  manual_review_comment: string | null;
  reviewer_id: number | null;
  reviewed_at: string | null;
}

// =============================================================================
// C15 report-export 类型
// =============================================================================

/** GET /reports/{version}/dimensions 单行 */
export interface ReportDimensionDetail {
  dimension: string;
  best_score: number;
  is_ironclad: boolean;
  evidence_summary: string;
  manual_review_json: {
    action: "confirmed" | "rejected" | "note";
    comment: string | null;
    reviewer_id: number;
    at: string;
  } | null;
}

export interface ReportDimensionsResponse {
  dimensions: ReportDimensionDetail[];
}

/** GET /reports/{version}/pairs */
export interface PairComparisonItem {
  id: number;
  dimension: string;
  bidder_a_id: number;
  bidder_b_id: number;
  score: number;
  is_ironclad: boolean;
  evidence_summary: string | null;
}

export interface PairsResponse {
  items: PairComparisonItem[];
}

/** GET /reports/{version}/logs 合并条目 */
export interface LogEntry {
  source: "agent_task" | "audit_log";
  created_at: string;
  payload: Record<string, unknown>;
}

export interface LogsResponse {
  items: LogEntry[];
}

/** 复核 API body/response */
export type ReviewStatus = "confirmed" | "rejected" | "downgraded" | "upgraded";

export interface ReviewIn {
  status: ReviewStatus;
  comment?: string;
}

export interface ReviewOut {
  manual_review_status: ReviewStatus;
  manual_review_comment: string | null;
  reviewer_id: number;
  reviewed_at: string;
}

export type DimensionReviewAction = "confirmed" | "rejected" | "note";

export interface DimensionReviewIn {
  action: DimensionReviewAction;
  comment?: string;
}

/** 导出 */
export interface ExportStartOut {
  job_id: number;
}

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
  | "needs_password";

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
  file_role: string | null;
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
}

export interface ProjectProgress {
  total_bidders: number;
  pending_count: number;
  extracting_count: number;
  extracted_count: number;
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

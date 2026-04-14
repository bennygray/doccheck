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

/** 详情返回含 C4+ 预留占位字段 */
export interface ProjectDetail extends Project {
  bidders: unknown[];
  files: unknown[];
  progress: unknown | null;
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

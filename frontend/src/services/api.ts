/**
 * API client with auth interceptor (C2).
 *
 * - 自动挂 `Authorization: Bearer <token>`,token 从 authStorage 取(避免循环 import context)
 * - 响应 401 → 清 token + 记 pendingPath + 触发 onUnauthorized 回调(由 App 注入 navigate)
 *
 * 保留 C1 现有接口(health/projects/documents/analysis),C3+ 改造时替换。
 */
import { authStorage } from "../contexts/AuthContext";
import type {
  AdminUser,
  AnalysisStartResponse,
  AnalysisStatusResponse,
  BidDocument,
  Bidder,
  BidderListResponse,
  CreateUserPayload,
  DimensionReviewIn,
  DocumentRole,
  DocumentRolePatchResult,
  ExportStartOut,
  LLMConfigResponse,
  LLMConfigUpdate,
  LLMTestRequest,
  LLMTestResponse,
  LogsResponse,
  MetaCompareResponse,
  PairsResponse,
  PriceCompareResponse,
  PriceConfig,
  RulesConfig,
  RulesConfigResponse,
  TenderDocument,
  TenderUploadResult,
  TextCompareResponse,
  PriceConfigPayload,
  PriceItem,
  PriceParsingRule,
  PriceParsingRulePayload,
  Project,
  ProjectCreatePayload,
  ProjectDetail,
  ProjectListQuery,
  ProjectListResponse,
  ReportDimensionsResponse,
  ReportResponse,
  ReviewIn,
  ReviewOut,
  UpdateUserPayload,
  UploadResult,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

export function setOnUnauthorized(h: UnauthorizedHandler | null) {
  onUnauthorized = h;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (!headers.has("Content-Type") && options?.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = authStorage.getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    // 记住当前路径,登录成功后恢复
    try {
      authStorage.setPendingPath(window.location.pathname + window.location.search);
    } catch {
      // ignore
    }
    authStorage.clear();
    onUnauthorized?.();
    throw new ApiError(401, "unauthorized");
  }

  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json())?.detail ?? res.statusText;
    } catch {
      // body 可能非 JSON
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    const detailStr =
      typeof detail === "string" ? detail : JSON.stringify(detail);
    super(`API error ${status}: ${detailStr}`);
    this.status = status;
    this.detail = detail;
  }
}

export interface User {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export const api = {
  // C1 infra
  health: () => request<{ status: string; db: string }>("/health"),

  // C2 auth
  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  changePassword: (old_password: string, new_password: string) =>
    request<User>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ old_password, new_password }),
    }),

  // C3 project-mgmt
  listProjects: (q?: ProjectListQuery) => {
    const params = new URLSearchParams();
    if (q?.page != null) params.set("page", String(q.page));
    if (q?.size != null) params.set("size", String(q.size));
    if (q?.status) params.set("status", q.status);
    if (q?.risk_level) params.set("risk_level", q.risk_level);
    if (q?.search) params.set("search", q.search);
    const qs = params.toString();
    return request<ProjectListResponse>(`/projects/${qs ? `?${qs}` : ""}`);
  },
  createProject: (payload: ProjectCreatePayload) =>
    request<Project>("/projects/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getProject: (id: number | string) =>
    request<ProjectDetail>(`/projects/${id}`),
  deleteProject: (id: number | string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),

  // ==========================================================================
  // C4 file-upload — bidders / documents / price
  // ==========================================================================

  listBidders: (projectId: number | string) =>
    request<BidderListResponse>(`/projects/${projectId}/bidders/`),

  /**
   * 创建投标人;同一 multipart 请求里可附带一个文件(US-3.1 一步完成)。
   * 不传 file → 仅创建空投标人。
   */
  createBidder: async (
    projectId: number | string,
    name: string,
    file?: File | null,
  ): Promise<Bidder> => {
    const fd = new FormData();
    fd.append("name", name);
    if (file) fd.append("file", file);
    const headers = new Headers();
    const token = authStorage.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch(`${API_BASE}/projects/${projectId}/bidders/`, {
      method: "POST",
      body: fd,
      headers,
    });
    if (res.status === 401) {
      authStorage.clear();
      onUnauthorized?.();
      throw new ApiError(401, "unauthorized");
    }
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        detail = (await res.json())?.detail ?? res.statusText;
      } catch {
        // body 可能非 JSON
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as Bidder;
  },

  getBidder: (projectId: number | string, bidderId: number | string) =>
    request<Bidder>(`/projects/${projectId}/bidders/${bidderId}`),

  deleteBidder: (projectId: number | string, bidderId: number | string) =>
    request<void>(`/projects/${projectId}/bidders/${bidderId}`, {
      method: "DELETE",
    }),

  /** 已有投标人追加上传(US-3.2)。 */
  uploadToBidder: async (
    projectId: number | string,
    bidderId: number | string,
    file: File,
  ): Promise<UploadResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const headers = new Headers();
    const token = authStorage.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch(
      `${API_BASE}/projects/${projectId}/bidders/${bidderId}/upload`,
      { method: "POST", body: fd, headers },
    );
    if (res.status === 401) {
      authStorage.clear();
      onUnauthorized?.();
      throw new ApiError(401, "unauthorized");
    }
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        detail = (await res.json())?.detail ?? res.statusText;
      } catch {
        // body 可能非 JSON
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as UploadResult;
  },

  listDocuments: (projectId: number | string, bidderId: number | string) =>
    request<BidDocument[]>(
      `/projects/${projectId}/bidders/${bidderId}/documents`,
    ),

  deleteDocument: (documentId: number | string) =>
    request<void>(`/documents/${documentId}`, { method: "DELETE" }),

  downloadDocument: (documentId: number | string) =>
    `${API_BASE}/documents/${documentId}/download`,

  decryptDocument: (documentId: number | string, password: string) =>
    request<{ detail: string }>(`/documents/${documentId}/decrypt`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  getPriceConfig: (projectId: number | string) =>
    request<PriceConfig | null>(`/projects/${projectId}/price-config`),

  putPriceConfig: (projectId: number | string, payload: PriceConfigPayload) =>
    request<PriceConfig>(`/projects/${projectId}/price-config`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  listPriceRules: (projectId: number | string) =>
    request<PriceParsingRule[]>(`/projects/${projectId}/price-rules`),

  putPriceRule: (
    projectId: number | string,
    payload: PriceParsingRulePayload,
  ) =>
    request<PriceParsingRule>(`/projects/${projectId}/price-rules`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // ===========================================================================
  // C5 parser-pipeline 新增
  // ===========================================================================

  /** PATCH /api/documents/{id}/role — 修改文档角色 */
  patchDocumentRole: (
    documentId: number | string,
    role: DocumentRole,
  ) =>
    request<DocumentRolePatchResult>(`/documents/${documentId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  /** POST /api/documents/{id}/re-parse — 重新解析失败/跳过文档 */
  reParseDocument: (documentId: number | string) =>
    request<{ detail: string }>(`/documents/${documentId}/re-parse`, {
      method: "POST",
    }),

  /** PUT /api/projects/{pid}/price-rules/{id} — 修正并重新回填 */
  putPriceRuleById: (
    projectId: number | string,
    ruleId: number | string,
    payload: PriceParsingRulePayload,
  ) =>
    request<PriceParsingRule>(
      `/projects/${projectId}/price-rules/${ruleId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  /** GET /api/projects/{pid}/bidders/{bid}/price-items — 报价项列表 */
  listPriceItems: (
    projectId: number | string,
    bidderId: number | string,
  ) =>
    request<PriceItem[]>(
      `/projects/${projectId}/bidders/${bidderId}/price-items`,
    ),

  /** GET /api/projects/{pid}/parse-progress(SSE URL,EventSource 用) */
  parseProgressUrl: (projectId: number | string) =>
    `${API_BASE}/projects/${projectId}/parse-progress`,

  // ===========================================================================
  // C6 detect-framework 新增
  // ===========================================================================

  /** POST /api/projects/{pid}/analysis/start — 启动检测 */
  startAnalysis: (projectId: number | string) =>
    request<AnalysisStartResponse>(`/projects/${projectId}/analysis/start`, {
      method: "POST",
    }),

  /** GET /api/projects/{pid}/analysis/status — 检测状态快照 */
  getAnalysisStatus: (projectId: number | string) =>
    request<AnalysisStatusResponse>(`/projects/${projectId}/analysis/status`),

  /** SSE URL:GET /api/projects/{pid}/analysis/events */
  analysisEventsUrl: (projectId: number | string) =>
    `${API_BASE}/projects/${projectId}/analysis/events`,

  /** GET /api/projects/{pid}/reports/{version} — 报告骨架 */
  getReport: (projectId: number | string, version: number | string) =>
    request<ReportResponse>(`/projects/${projectId}/reports/${version}`),

  // ---------------------------------------------------------- C15

  /** GET /reports/{version}/dimensions — 13 维度明细 */
  getReportDimensions: (
    projectId: number | string,
    version: number | string,
  ) =>
    request<ReportDimensionsResponse>(
      `/projects/${projectId}/reports/${version}/dimensions`,
    ),

  /** GET /reports/{version}/pairs — pair 摘要 */
  getReportPairs: (
    projectId: number | string,
    version: number | string,
    sort: "score_desc" | "id_asc" = "score_desc",
    limit = 50,
  ) =>
    request<PairsResponse>(
      `/projects/${projectId}/reports/${version}/pairs?sort=${sort}&limit=${limit}`,
    ),

  /** GET /reports/{version}/logs — AgentTask + AuditLog 合并 */
  getReportLogs: (
    projectId: number | string,
    version: number | string,
    source: "all" | "agent_task" | "audit_log" = "all",
    limit = 100,
  ) =>
    request<LogsResponse>(
      `/projects/${projectId}/reports/${version}/logs?source=${source}&limit=${limit}`,
    ),

  /** POST 整报告级复核 */
  postReview: (
    projectId: number | string,
    version: number | string,
    body: ReviewIn,
  ) =>
    request<ReviewOut>(
      `/projects/${projectId}/reports/${version}/review`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  /** POST 维度级复核 */
  postDimensionReview: (
    projectId: number | string,
    version: number | string,
    dimension: string,
    body: DimensionReviewIn,
  ) =>
    request<{ dimension: string; manual_review_json: unknown }>(
      `/projects/${projectId}/reports/${version}/dimensions/${dimension}/review`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  /** POST 触发 Word 导出 */
  startExport: (
    projectId: number | string,
    version: number | string,
    template_id?: number,
  ) =>
    request<ExportStartOut>(
      `/projects/${projectId}/reports/${version}/export`,
      {
        method: "POST",
        body: JSON.stringify({ template_id: template_id ?? null }),
      },
    ),

  /**
   * 下载导出文件:浏览器直接导航(window.open / <a href>)不会带 Authorization 头,
   * 这里把 JWT 塞进 access_token query param(后端 get_current_user 已支持该回退,
   * 和 SSE EventSource 用的是同一条 auth 回退路径)
   */
  downloadExportUrl: (jobId: number) => {
    const base = `${API_BASE}/exports/${jobId}/download`;
    const token = authStorage.getToken();
    return token ? `${base}?access_token=${encodeURIComponent(token)}` : base;
  },

  // ---------------------------------------------------------- C16 compare-view

  /** GET /compare/text — 文本对比(pair 级) */
  getCompareText: (
    projectId: number | string,
    bidderA: number,
    bidderB: number,
    docRole?: string,
    version?: number | string,
  ) => {
    const params = new URLSearchParams({
      bidder_a: String(bidderA),
      bidder_b: String(bidderB),
    });
    if (docRole) params.set("doc_role", docRole);
    if (version !== undefined) params.set("version", String(version));
    return request<TextCompareResponse>(
      `/projects/${projectId}/compare/text?${params}`,
    );
  },

  /** GET /compare/price — 报价对比(全项目级) */
  getComparePrice: (
    projectId: number | string,
    version?: number | string,
  ) => {
    const params = version !== undefined ? `?version=${version}` : "";
    return request<PriceCompareResponse>(
      `/projects/${projectId}/compare/price${params}`,
    );
  },

  /** GET /compare/metadata — 元数据对比(全项目级) */
  getCompareMetadata: (
    projectId: number | string,
    version?: number | string,
  ) => {
    const params = version !== undefined ? `?version=${version}` : "";
    return request<MetaCompareResponse>(
      `/projects/${projectId}/compare/metadata${params}`,
    );
  },

  // ── Admin (C17) ──

  /** GET /admin/users */
  getUsers: () => request<AdminUser[]>("/admin/users"),

  /** POST /admin/users */
  createUser: (payload: CreateUserPayload) =>
    request<AdminUser>("/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** PATCH /admin/users/:id */
  updateUser: (id: number, payload: UpdateUserPayload) =>
    request<AdminUser>(`/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  /** GET /admin/rules */
  getRules: () => request<RulesConfigResponse>("/admin/rules"),

  /** PUT /admin/rules */
  updateRules: (config: RulesConfig | { restore_defaults: true }) =>
    request<RulesConfigResponse>("/admin/rules", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  /** GET /admin/llm (admin-llm-config) */
  getLLMConfig: () => request<LLMConfigResponse>("/admin/llm"),

  /** PUT /admin/llm */
  updateLLMConfig: (payload: LLMConfigUpdate) =>
    request<LLMConfigResponse>("/admin/llm", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  /** POST /admin/llm/test */
  testLLMConnection: (payload: LLMTestRequest) =>
    request<LLMTestResponse>("/admin/llm/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ===========================================================================
  // detect-tender-baseline §7:招标文件 (tender) 客户端
  // ===========================================================================

  listTenders: (projectId: number | string) =>
    request<TenderDocument[]>(`/projects/${projectId}/tender/`),

  /** POST /api/projects/{pid}/tender — 上传招标文件(multipart) */
  uploadTender: async (
    projectId: number | string,
    file: File,
  ): Promise<TenderUploadResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const headers = new Headers();
    const token = authStorage.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch(`${API_BASE}/projects/${projectId}/tender/`, {
      method: "POST",
      body: fd,
      headers,
    });
    if (res.status === 401) {
      authStorage.clear();
      onUnauthorized?.();
      throw new ApiError(401, "unauthorized");
    }
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        detail = (await res.json())?.detail ?? res.statusText;
      } catch {
        // body 可能非 JSON
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as TenderUploadResult;
  },

  deleteTender: (projectId: number | string, tenderId: number | string) =>
    request<void>(`/projects/${projectId}/tender/${tenderId}`, {
      method: "DELETE",
    }),
};

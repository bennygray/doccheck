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
  BidDocument,
  Bidder,
  BidderListResponse,
  PriceConfig,
  PriceConfigPayload,
  PriceParsingRule,
  PriceParsingRulePayload,
  Project,
  ProjectCreatePayload,
  ProjectDetail,
  ProjectListQuery,
  ProjectListResponse,
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
};

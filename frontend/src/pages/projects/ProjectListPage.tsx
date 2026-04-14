/**
 * 项目列表页 (C3 project-mgmt, US-2.2)
 *
 * 功能:
 * - 真实列表(卡片网格),支持分页 / 状态筛选 / 风险筛选 / 关键词搜索
 * - "新建项目"按钮 → /projects/new
 * - 每行"删除"按钮 → 二次确认 → api.deleteProject(软删)
 * - 空态引导 "暂无项目,点击新建"
 * - 顶部复用 C2 的欢迎 + 登出(与 ProjectsPlaceholderPage 一致)
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../../services/api";
import { useAuth } from "../../contexts/AuthContext";
import type { ProjectListItem, ProjectListResponse } from "../../types";

const PAGE_SIZE = 12;

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  parsing: "解析中",
  ready: "待检测",
  analyzing: "检测中",
  completed: "已完成",
};

const RISK_LABELS: Record<string, string> = {
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

const RISK_COLORS: Record<string, string> = {
  high: "#c00",
  medium: "#e67e22",
  low: "#2ecc71",
};

export default function ProjectListPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [items, setItems] = useState<ProjectListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [submittedSearch, setSubmittedSearch] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res: ProjectListResponse = await api.listProjects({
        page,
        size: PAGE_SIZE,
        status: statusFilter || undefined,
        risk_level: riskFilter || undefined,
        search: submittedSearch || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`加载失败 (${err.status})`);
      } else {
        setError("加载失败,请稍后重试");
      }
    } finally {
      setIsLoading(false);
    }
  }, [page, statusFilter, riskFilter, submittedSearch]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onLogout() {
    try {
      await api.logout();
    } catch {
      // 前端登出优先
    }
    logout();
    navigate("/login", { replace: true });
  }

  async function onDelete(p: ProjectListItem) {
    const ok = window.confirm(`确定删除项目 "${p.name}" 吗?该操作会隐藏项目(软删除)。`);
    if (!ok) return;
    try {
      await api.deleteProject(p.id);
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        window.alert("检测进行中,无法删除");
      } else if (err instanceof ApiError) {
        window.alert(`删除失败 (${err.status})`);
      } else {
        window.alert("删除失败,请稍后重试");
      }
    }
  }

  function onSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setSubmittedSearch(search.trim());
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <h1 style={{ fontSize: 24, margin: 0 }}>项目列表</h1>
        <div>
          <span data-testid="welcome-user" style={{ marginRight: 12 }}>
            欢迎,{user?.username}
          </span>
          <button
            onClick={onLogout}
            data-testid="logout-btn"
            style={{ padding: "6px 12px", cursor: "pointer" }}
          >
            登出
          </button>
        </div>
      </header>

      <section
        style={{
          marginTop: 24,
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <Link
          to="/projects/new"
          data-testid="new-project-btn"
          style={{
            padding: "8px 16px",
            background: "#1677ff",
            color: "#fff",
            textDecoration: "none",
            borderRadius: 4,
          }}
        >
          + 新建项目
        </Link>

        <label>
          <span style={{ marginRight: 4 }}>状态:</span>
          <select
            value={statusFilter}
            onChange={(e) => {
              setPage(1);
              setStatusFilter(e.target.value);
            }}
            data-testid="filter-status"
          >
            <option value="">全部</option>
            {Object.entries(STATUS_LABELS).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span style={{ marginRight: 4 }}>风险:</span>
          <select
            value={riskFilter}
            onChange={(e) => {
              setPage(1);
              setRiskFilter(e.target.value);
            }}
            data-testid="filter-risk"
          >
            <option value="">全部</option>
            {Object.entries(RISK_LABELS).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <form onSubmit={onSearchSubmit} style={{ display: "inline-flex", gap: 4 }}>
          <input
            type="text"
            placeholder="按名称/招标编号搜索"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="search-input"
            style={{ padding: 6 }}
          />
          <button type="submit" data-testid="search-submit" style={{ padding: "6px 10px" }}>
            搜索
          </button>
        </form>
      </section>

      <section style={{ marginTop: 24 }}>
        {error ? (
          <p data-testid="list-error" style={{ color: "#c00" }}>
            {error}
          </p>
        ) : null}

        {isLoading ? (
          <p data-testid="list-loading">加载中...</p>
        ) : items.length === 0 ? (
          <div data-testid="empty-state" style={{ padding: 24, color: "#666" }}>
            <p>暂无项目</p>
            <Link to="/projects/new">点击新建 →</Link>
          </div>
        ) : (
          <div
            data-testid="project-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: 16,
            }}
          >
            {items.map((p) => (
              <article
                key={p.id}
                data-testid={`project-card-${p.id}`}
                style={{
                  border: "1px solid #ddd",
                  borderRadius: 4,
                  padding: 12,
                  background: "#fff",
                }}
              >
                <Link
                  to={`/projects/${p.id}`}
                  style={{
                    fontWeight: 600,
                    fontSize: 16,
                    color: "#111",
                    textDecoration: "none",
                  }}
                >
                  {p.name}
                </Link>
                <div style={{ fontSize: 13, color: "#666", marginTop: 4 }}>
                  {p.bid_code ?? "(无招标编号)"}
                </div>
                <div style={{ fontSize: 13, marginTop: 8 }}>
                  状态:{STATUS_LABELS[p.status] ?? p.status}
                </div>
                <div style={{ fontSize: 13, marginTop: 4 }}>
                  风险:
                  {p.risk_level ? (
                    <span
                      style={{
                        color: RISK_COLORS[p.risk_level] ?? "#999",
                        marginLeft: 4,
                      }}
                    >
                      {RISK_LABELS[p.risk_level] ?? p.risk_level}
                    </span>
                  ) : (
                    <span style={{ color: "#999", marginLeft: 4 }}>未检测</span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#999", marginTop: 8 }}>
                  创建时间:{new Date(p.created_at).toLocaleString()}
                </div>
                <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                  <Link
                    to={`/projects/${p.id}`}
                    data-testid={`project-open-${p.id}`}
                    style={{
                      fontSize: 13,
                      padding: "4px 8px",
                      background: "#f5f5f5",
                      textDecoration: "none",
                      color: "#111",
                      borderRadius: 3,
                    }}
                  >
                    查看
                  </Link>
                  <button
                    onClick={() => onDelete(p)}
                    data-testid={`project-delete-${p.id}`}
                    style={{
                      fontSize: 13,
                      padding: "4px 8px",
                      background: "#fff0f0",
                      color: "#c00",
                      border: "1px solid #f5c0c0",
                      borderRadius: 3,
                      cursor: "pointer",
                    }}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {total > PAGE_SIZE ? (
        <nav
          data-testid="pagination"
          style={{ marginTop: 24, display: "flex", gap: 8, alignItems: "center" }}
        >
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            data-testid="page-prev"
          >
            上一页
          </button>
          <span data-testid="page-info">
            第 {page} / {totalPages} 页(共 {total} 条)
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            data-testid="page-next"
          >
            下一页
          </button>
        </nav>
      ) : null}
    </main>
  );
}

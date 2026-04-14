/**
 * 项目详情页 (C3 project-mgmt, US-2.3)
 *
 * C3 只渲染基础信息 + 状态徽章;
 * 投标人 / 文件 / 检测进度区以占位形式显式标注"待 C4 / C6 实现",
 * 避免用户对空区域产生误解。
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../../services/api";
import type { ProjectDetail } from "../../types";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  parsing: "解析中",
  ready: "待检测",
  analyzing: "检测中",
  completed: "已完成",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "#888",
  parsing: "#1677ff",
  ready: "#52c41a",
  analyzing: "#e67e22",
  completed: "#2ecc71",
};

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const p = await api.getProject(id);
      setProject(p);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError("项目不存在或已被删除");
      } else if (err instanceof ApiError) {
        setError(`加载失败 (${err.status})`);
      } else {
        setError("加载失败,请稍后重试");
      }
    } finally {
      setIsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDelete() {
    if (!project) return;
    const ok = window.confirm(
      `确定删除项目 "${project.name}" 吗?该操作会隐藏项目(软删除)。`,
    );
    if (!ok) return;
    setDeleting(true);
    try {
      await api.deleteProject(project.id);
      navigate("/projects", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        window.alert("检测进行中,无法删除");
      } else if (err instanceof ApiError) {
        window.alert(`删除失败 (${err.status})`);
      } else {
        window.alert("删除失败,请稍后重试");
      }
    } finally {
      setDeleting(false);
    }
  }

  if (isLoading) {
    return (
      <main style={{ padding: 32 }}>
        <p data-testid="detail-loading">加载中...</p>
      </main>
    );
  }

  if (error) {
    return (
      <main style={{ padding: 32 }}>
        <p data-testid="detail-error" style={{ color: "#c00" }}>
          {error}
        </p>
        <Link to="/projects">← 返回项目列表</Link>
      </main>
    );
  }

  if (!project) return null;

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif", maxWidth: 960 }}>
      <header style={{ marginBottom: 16 }}>
        <Link to="/projects" data-testid="back-to-list">
          ← 返回项目列表
        </Link>
      </header>

      <section
        data-testid="project-basic"
        style={{ borderBottom: "1px solid #eee", paddingBottom: 16 }}
      >
        <h1 style={{ fontSize: 24, margin: 0 }} data-testid="project-name">
          {project.name}
        </h1>
        <div style={{ display: "flex", gap: 16, marginTop: 8, flexWrap: "wrap" }}>
          <span>
            状态:
            <span
              data-testid="project-status"
              style={{
                color: STATUS_COLORS[project.status] ?? "#333",
                marginLeft: 4,
                fontWeight: 500,
              }}
            >
              {STATUS_LABELS[project.status] ?? project.status}
            </span>
          </span>
          <span>
            招标编号:
            <span data-testid="project-bid-code" style={{ marginLeft: 4 }}>
              {project.bid_code ?? "(无)"}
            </span>
          </span>
          <span>
            最高限价:
            <span data-testid="project-max-price" style={{ marginLeft: 4 }}>
              {project.max_price ?? "(未设置)"}
            </span>
          </span>
        </div>
        {project.description ? (
          <p
            data-testid="project-description"
            style={{ marginTop: 12, color: "#444" }}
          >
            {project.description}
          </p>
        ) : null}
        <div style={{ fontSize: 12, color: "#999", marginTop: 8 }}>
          创建时间:{new Date(project.created_at).toLocaleString()}
        </div>

        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <button
            onClick={onDelete}
            disabled={deleting}
            data-testid="detail-delete"
            style={{
              padding: "6px 12px",
              background: "#fff0f0",
              color: "#c00",
              border: "1px solid #f5c0c0",
              cursor: deleting ? "not-allowed" : "pointer",
            }}
          >
            {deleting ? "删除中..." : "删除项目"}
          </button>
        </div>
      </section>

      <section
        data-testid="bidders-placeholder"
        style={{ marginTop: 24, padding: 16, background: "#fafafa", borderRadius: 4 }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>投标人管理</h2>
        <p style={{ color: "#888", marginTop: 4 }}>
          待 C4 file-upload 上线后,此处将显示投标人列表与文件上传入口。
        </p>
      </section>

      <section
        data-testid="files-placeholder"
        style={{ marginTop: 12, padding: 16, background: "#fafafa", borderRadius: 4 }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>文件管理</h2>
        <p style={{ color: "#888", marginTop: 4 }}>
          待 C4 file-upload / C5 parser-pipeline 上线后,此处显示每个投标人的文件与解析状态。
        </p>
      </section>

      <section
        data-testid="progress-placeholder"
        style={{ marginTop: 12, padding: 16, background: "#fafafa", borderRadius: 4 }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>检测进度</h2>
        <p style={{ color: "#888", marginTop: 4 }}>
          待 C6 detect-framework 上线后,此处显示 Agent 并行执行的 SSE 进度。
        </p>
      </section>
    </main>
  );
}

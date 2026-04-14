/**
 * 项目详情页 (C3 base + C4 file-upload §9.1)。
 *
 * C4 起替换 bidders/files/progress 三处占位:
 * - 投标人卡片列表 + 添加投标人按钮 + 每张卡片含 UploadButton + FileTree + 删除
 * - progress 顶部聚合统计
 * - 报价规则 section(PriceConfigForm + PriceRulesPlaceholder)
 * - bidder.parse_status=extracting 时启动 2s 轮询,自动消失
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import AddBidderDialog from "../../components/projects/AddBidderDialog";
import DecryptDialog from "../../components/projects/DecryptDialog";
import FileTree from "../../components/projects/FileTree";
import PriceConfigForm from "../../components/projects/PriceConfigForm";
import PriceRulesPlaceholder from "../../components/projects/PriceRulesPlaceholder";
import UploadButton from "../../components/projects/UploadButton";
import { ApiError, api } from "../../services/api";
import type { BidDocument, Bidder, ProjectDetail } from "../../types";

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

const POLL_INTERVAL_MS = 2000;

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // bidder 文件树展开:bidderId -> documents 缓存
  const [docsByBidder, setDocsByBidder] = useState<Record<number, BidDocument[]>>({});
  const [showAddBidder, setShowAddBidder] = useState(false);
  const [decryptTarget, setDecryptTarget] = useState<BidDocument | null>(null);
  const [bidders, setBidders] = useState<Bidder[]>([]);
  const pollRef = useRef<number | null>(null);

  const projectId = id ? Number(id) : NaN;

  const reloadProject = useCallback(async () => {
    if (!id) return;
    try {
      const p = await api.getProject(id);
      setProject(p);
      const list = await api.listBidders(id);
      setBidders(list.items);
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

  const reloadDocs = useCallback(
    async (bidderId: number) => {
      if (!id) return;
      try {
        const docs = await api.listDocuments(id, bidderId);
        setDocsByBidder((p) => ({ ...p, [bidderId]: docs }));
      } catch {
        // 单独 bidder 拉取失败不阻塞主页
      }
    },
    [id],
  );

  useEffect(() => {
    void reloadProject();
  }, [reloadProject]);

  // 轮询:任一 bidder 处于 extracting/pending → 2s 再拉一次
  useEffect(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    const needsPoll = bidders.some((b) =>
      ["extracting", "pending"].includes(b.parse_status),
    );
    if (!needsPoll) return;
    pollRef.current = window.setInterval(() => {
      void reloadProject();
      bidders
        .filter((b) => ["extracting", "pending"].includes(b.parse_status))
        .forEach((b) => void reloadDocs(b.id));
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [bidders, reloadProject, reloadDocs]);

  async function onDeleteProject() {
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

  async function onDeleteBidder(bidderId: number, bidderName: string) {
    const ok = window.confirm(`确定删除投标人 "${bidderName}"?其所有解压文件会被清除。`);
    if (!ok) return;
    try {
      await api.deleteBidder(projectId, bidderId);
      await reloadProject();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        window.alert("检测进行中,无法删除投标人");
      } else if (err instanceof ApiError) {
        window.alert(`删除失败 (${err.status})`);
      } else {
        window.alert("删除失败");
      }
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

  const progress = project.progress;

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
          <p data-testid="project-description" style={{ marginTop: 12, color: "#444" }}>
            {project.description}
          </p>
        ) : null}
        <div style={{ fontSize: 12, color: "#999", marginTop: 8 }}>
          创建时间:{new Date(project.created_at).toLocaleString()}
        </div>

        <div style={{ marginTop: 16 }}>
          <button
            onClick={onDeleteProject}
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

      {progress && (
        <section
          data-testid="progress-summary"
          style={{ marginTop: 16, padding: 12, background: "#f5f7fa", borderRadius: 4 }}
        >
          <strong>解析进度:</strong>{" "}
          <span data-testid="progress-total">投标人 {progress.total_bidders}</span>
          {" / "}
          <span data-testid="progress-extracted">已解析 {progress.extracted_count}</span>
          {" / "}
          <span data-testid="progress-extracting">解析中 {progress.extracting_count}</span>
          {" / "}
          <span data-testid="progress-needs-password">需密码 {progress.needs_password_count}</span>
          {" / "}
          <span data-testid="progress-failed">失败 {progress.failed_count}</span>
        </section>
      )}

      <section
        data-testid="bidders-section"
        style={{ marginTop: 24 }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h2 style={{ fontSize: 16, margin: 0 }}>投标人管理</h2>
          <button
            onClick={() => setShowAddBidder(true)}
            data-testid="open-add-bidder"
            style={{ padding: "4px 12px", background: "#1677ff", color: "#fff", border: 0 }}
          >
            + 添加投标人
          </button>
        </div>
        {bidders.length === 0 ? (
          <p
            data-testid="bidders-empty"
            style={{ color: "#888", marginTop: 8 }}
          >
            还没有投标人,点击右上角添加第一个。
          </p>
        ) : (
          <ul style={{ padding: 0, listStyle: "none", marginTop: 12 }}>
            {bidders.map((b) => (
              <li
                key={b.id}
                data-testid={`bidder-card-${b.id}`}
                style={{
                  border: "1px solid #ddd",
                  borderRadius: 4,
                  padding: 12,
                  marginBottom: 8,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: 12,
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <strong data-testid={`bidder-name-${b.id}`}>{b.name}</strong>
                    <span
                      data-testid={`bidder-status-${b.id}`}
                      style={{
                        fontSize: 11,
                        padding: "0 6px",
                        background: STATUS_COLORS[b.parse_status] ?? "#aaa",
                        color: "#fff",
                        borderRadius: 8,
                      }}
                    >
                      {b.parse_status}
                    </span>
                    <span style={{ color: "#888", fontSize: 12 }}>
                      {b.file_count} 个文件
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <UploadButton
                      projectId={projectId}
                      bidderId={b.id}
                      onUploaded={() => {
                        void reloadProject();
                        void reloadDocs(b.id);
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => void reloadDocs(b.id)}
                      data-testid={`bidder-refresh-${b.id}`}
                      style={{ padding: "4px 12px" }}
                    >
                      刷新文件
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteBidder(b.id, b.name)}
                      data-testid={`bidder-delete-${b.id}`}
                      style={{
                        padding: "4px 12px",
                        background: "#fff0f0",
                        color: "#c00",
                        border: "1px solid #f5c0c0",
                      }}
                    >
                      删除
                    </button>
                  </div>
                </div>
                {b.parse_status === "needs_password" && (
                  <div style={{ marginTop: 8 }}>
                    <button
                      type="button"
                      data-testid={`open-decrypt-${b.id}`}
                      onClick={() => {
                        const archive = (docsByBidder[b.id] ?? []).find(
                          (d) => d.parse_status === "needs_password",
                        );
                        if (archive) setDecryptTarget(archive);
                        else void reloadDocs(b.id);
                      }}
                      style={{ background: "#722ed1", color: "#fff", border: 0, padding: "4px 12px" }}
                    >
                      输入密码解密
                    </button>
                  </div>
                )}
                {b.parse_error && (
                  <div style={{ color: "#c00", marginTop: 8, fontSize: 12 }}>
                    {b.parse_error}
                  </div>
                )}
                {docsByBidder[b.id] && (
                  <div style={{ marginTop: 8 }}>
                    <FileTree documents={docsByBidder[b.id]} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        data-testid="price-section"
        style={{ marginTop: 24, padding: 16, background: "#fafafa", borderRadius: 4 }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>报价规则</h2>
        <div style={{ marginTop: 12 }}>
          <PriceConfigForm projectId={projectId} />
        </div>
        <div style={{ marginTop: 12 }}>
          <PriceRulesPlaceholder projectId={projectId} />
        </div>
      </section>

      {showAddBidder && (
        <AddBidderDialog
          projectId={projectId}
          onClose={() => setShowAddBidder(false)}
          onCreated={() => {
            setShowAddBidder(false);
            void reloadProject();
          }}
        />
      )}
      {decryptTarget && (
        <DecryptDialog
          documentId={decryptTarget.id}
          fileName={decryptTarget.file_name}
          onClose={() => setDecryptTarget(null)}
          onSubmitted={() => {
            setDecryptTarget(null);
            void reloadProject();
          }}
        />
      )}
    </main>
  );
}

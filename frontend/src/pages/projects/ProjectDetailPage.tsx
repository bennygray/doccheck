/**
 * 项目详情页 (C3 base + C4 file-upload §9.1 + C5/C6 扩展)
 *
 * UX 重设:
 *  - Hero 信息卡(合并原"基本信息 + 检测 + 解析进度"三卡):左侧元数据 + 右侧主 CTA(启动检测)+ 条件底行(解析进度 / 检测进度 / 报告入口)
 *  - 投标人管理:紧凑行列表,点击行打开右侧 Drawer(文件树 + 角色编辑 + 解密入口)
 *  - 报价规则:保留,作为独立底部卡
 *
 * 业务逻辑 0 改动:SSE / 轮询 / Dialog / UploadButton / FileTree / DetectSection 全量沿用
 * data-testid 全保留
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  App,
  Breadcrumb,
  Button,
  Card,
  Drawer,
  Empty,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  CalendarOutlined,
  DeleteOutlined,
  DollarOutlined,
  FileTextOutlined,
  InfoCircleOutlined,
  LockOutlined,
  NumberOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
} from "@ant-design/icons";
import AddBidderDialog from "../../components/projects/AddBidderDialog";
import DecryptDialog from "../../components/projects/DecryptDialog";
import FileTree from "../../components/projects/FileTree";
import ParseProgressIndicator from "../../components/projects/ParseProgressIndicator";
import PriceConfigForm from "../../components/projects/PriceConfigForm";
import PriceRulesPanel from "../../components/projects/PriceRulesPanel";
import RerunAfterTenderDialog from "../../components/projects/RerunAfterTenderDialog";
import TenderUploadCard from "../../components/projects/TenderUploadCard";
import UploadButton from "../../components/projects/UploadButton";
import { DetectProgressIndicator } from "../../components/detect/DetectProgressIndicator";
import { StartDetectButton } from "../../components/detect/StartDetectButton";
import { useDetectProgress } from "../../hooks/useDetectProgress";
import { useParseProgress } from "../../hooks/useParseProgress";
import { ApiError, api } from "../../services/api";
import type { BidDocument, Bidder, ProjectDetail } from "../../types";
import { isTenderBaselineEnabled } from "../../utils/featureFlags";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  parsing: "解析中",
  ready: "待检测",
  analyzing: "检测中",
  completed: "已完成",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  parsing: "processing",
  ready: "blue",
  analyzing: "processing",
  completed: "success",
};

const BIDDER_STATUS_LABELS: Record<string, string> = {
  pending: "待解析",
  extracting: "解析中",
  extracted: "已解压",
  identifying: "识别中",
  identified: "已识别",
  pricing: "报价中",
  priced: "已报价",
  needs_password: "需密码",
  failed: "失败",
  partial: "部分成功",
};

const BIDDER_STATUS_COLORS: Record<string, string> = {
  pending: "default",
  extracting: "processing",
  extracted: "blue",
  identifying: "processing",
  identified: "cyan",
  pricing: "processing",
  priced: "success",
  needs_password: "warning",
  failed: "error",
  partial: "warning",
};

const POLL_INTERVAL_MS = 2000;

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { modal, message } = App.useApp();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [docsByBidder, setDocsByBidder] = useState<Record<number, BidDocument[]>>({});
  const [showAddBidder, setShowAddBidder] = useState(false);
  const [decryptTarget, setDecryptTarget] = useState<BidDocument | null>(null);
  const [bidders, setBidders] = useState<Bidder[]>([]);
  // 侧边 Drawer 选中的投标人 id(null = 关闭)
  const [drawerBidderId, setDrawerBidderId] = useState<number | null>(null);
  // detect-tender-baseline §7:招标文件上传后,若已有完成版本则提示重跑
  const [showRerunDialog, setShowRerunDialog] = useState(false);
  const [rerunLoading, setRerunLoading] = useState(false);

  const tenderBaselineEnabled = isTenderBaselineEnabled();

  const pollRef = useRef<number | null>(null);

  const projectId = id ? Number(id) : NaN;

  const sse = useParseProgress(Number.isFinite(projectId) ? projectId : null);

  // fix-bug-triple-and-direction-high P7:lift useDetectProgress 到父组件,
  // 让 Tag 渲染处(STATUS_LABELS Tag,line ~346)能拿到 detect.projectStatus 实时同步。
  // HeroDetectArea / StartDetectButton 改 props 接收 detect 实例,refetch prop chain
  // 必须显式传(StartDetectButton onStarted 闭包要用)。
  const detect = useDetectProgress(
    Number.isFinite(projectId) ? projectId : null,
  );

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
        // ignore
      }
    },
    [id],
  );

  useEffect(() => {
    void reloadProject();
  }, [reloadProject]);

  // 打开 Drawer 时自动加载该投标人的文件(若尚未缓存)
  useEffect(() => {
    if (drawerBidderId !== null && !docsByBidder[drawerBidderId]) {
      void reloadDocs(drawerBidderId);
    }
  }, [drawerBidderId, docsByBidder, reloadDocs]);

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

  function onDeleteProject() {
    if (!project) return;
    modal.confirm({
      title: "删除项目",
      content: (
        <span>
          确定删除项目 <b>{project.name}</b>?该操作会隐藏项目(软删除)。
        </span>
      ),
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      async onOk() {
        setDeleting(true);
        try {
          await api.deleteProject(project.id);
          navigate("/projects", { replace: true });
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            void message.error("检测进行中,无法删除");
          } else if (err instanceof ApiError) {
            void message.error(`删除失败 (${err.status})`);
          } else {
            void message.error("删除失败,请稍后重试");
          }
        } finally {
          setDeleting(false);
        }
      },
    });
  }

  function onDeleteBidder(bidderId: number, bidderName: string) {
    modal.confirm({
      title: "删除投标人",
      content: (
        <span>
          确定删除投标人 <b>{bidderName}</b>?其所有解压文件会被清除。
        </span>
      ),
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      async onOk() {
        try {
          await api.deleteBidder(projectId, bidderId);
          // 若删除的是 Drawer 当前项,关 Drawer
          if (drawerBidderId === bidderId) setDrawerBidderId(null);
          await reloadProject();
          void message.success("已删除");
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            void message.error("检测进行中,无法删除投标人");
          } else if (err instanceof ApiError) {
            void message.error(`删除失败 (${err.status})`);
          } else {
            void message.error("删除失败");
          }
        }
      },
    });
  }

  // SSE 优先的 bidder 状态合并
  const mergedBidders = useMemo(
    () =>
      bidders.map((b) => {
        const sseMatch = sse.bidders.find((x) => x.id === b.id);
        return sseMatch ? { ...b, parse_status: sseMatch.parse_status } : b;
      }),
    [bidders, sse.bidders],
  );

  const drawerBidder =
    drawerBidderId !== null
      ? mergedBidders.find((b) => b.id === drawerBidderId) ?? null
      : null;

  if (isLoading) {
    return <div data-testid="detail-loading">加载中...</div>;
  }

  if (error) {
    return (
      <div>
        <Breadcrumb
          items={[
            { title: <Link to="/projects" data-testid="back-to-list">项目</Link> },
            { title: "详情" },
          ]}
          style={{ marginBottom: 12 }}
        />
        <Card>
          <Empty
            description={
              <span data-testid="detail-error" style={{ color: "#c53030" }}>
                {error}
              </span>
            }
          >
            <Link to="/projects">
              <Button type="primary">返回项目列表</Button>
            </Link>
          </Empty>
        </Card>
      </div>
    );
  }

  if (!project) return null;

  const progress = project.progress;

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects" data-testid="back-to-list">项目</Link> },
          { title: project.name },
        ]}
        style={{ marginBottom: 12 }}
      />

      {/* Hero:基本信息 + 主 CTA + 条件底行 */}
      <Card
        variant="outlined"
        data-testid="project-basic"
        styles={{ body: { padding: 0 } }}
        style={{ marginBottom: 16 }}
      >
        <div
          style={{
            padding: "20px 24px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 24,
            flexWrap: "wrap",
          }}
        >
          {/* 左:身份 + meta + 描述(每行独立 block,不会串在一起) */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* 标题行 */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                marginBottom: 10,
              }}
            >
              <Typography.Title
                level={3}
                style={{ margin: 0, fontWeight: 600, fontSize: 22 }}
                data-testid="project-name"
              >
                {project.name}
              </Typography.Title>
              <Tag
                color={
                  STATUS_COLORS[detect.projectStatus ?? project.status] ??
                  "default"
                }
                data-testid="project-status"
                style={{ margin: 0 }}
              >
                {STATUS_LABELS[detect.projectStatus ?? project.status] ??
                  (detect.projectStatus ?? project.status)}
              </Tag>
            </div>

            {/* Meta chip 行 */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 20,
                flexWrap: "wrap",
                marginBottom: project.description ? 10 : 0,
              }}
            >
              <MetaChip
                icon={<NumberOutlined />}
                label="编号"
                value={
                  <span data-testid="project-bid-code">
                    {project.bid_code ?? <span style={{ color: "#b1b6bf" }}>—</span>}
                  </span>
                }
              />
              <MetaChip
                icon={<DollarOutlined />}
                label="限价"
                value={
                  <span data-testid="project-max-price">
                    {project.max_price ?? (
                      <span style={{ color: "#b1b6bf" }}>未设置</span>
                    )}
                  </span>
                }
              />
              <MetaChip
                icon={<CalendarOutlined />}
                label="创建于"
                value={new Date(project.created_at).toLocaleString()}
              />
            </div>

            {project.description ? (
              <Typography.Paragraph
                type="secondary"
                style={{
                  margin: "4px 0 0",
                  fontSize: 13,
                  lineHeight: 1.7,
                }}
                data-testid="project-description"
              >
                {project.description}
              </Typography.Paragraph>
            ) : null}
          </div>

          {/* 右:删除(左) + 主 CTA(右),拉开间距避免误点 */}
          <div
            style={{
              display: "flex",
              gap: 4,
              alignItems: "center",
              flexShrink: 0,
            }}
          >
            <Tooltip title="删除项目">
              <Button
                danger
                type="text"
                icon={<DeleteOutlined />}
                onClick={onDeleteProject}
                loading={deleting}
                data-testid="detail-delete"
                aria-label="删除项目"
                style={{ height: 38, width: 38 }}
              />
            </Tooltip>
            {/* 视觉分隔线,避免删除和启动视觉上挨太近 */}
            <div
              aria-hidden="true"
              style={{
                width: 1,
                height: 24,
                background: "#e4e7ed",
                margin: "0 8px",
              }}
            />
            <HeroDetectArea
              projectId={project.id}
              project={project}
              bidders={mergedBidders}
              detect={detect}
              onReloadProject={() => void reloadProject()}
              onGoReport={(v) => navigate(`/reports/${project.id}/${v}`)}
            />
          </div>
        </div>

        {/* 条件底行:解析进度(仅当有 progress 时显示) */}
        {(sse.progress ?? progress) && (
          <div
            style={{
              borderTop: "1px solid #f0f2f5",
              padding: "14px 24px",
              background: "#fafbfc",
            }}
          >
            <ParseProgressIndicator
              progress={sse.progress ?? progress}
              connected={sse.connected}
            />
            {/* 保留 C4 data-testid 便于回归测试兼容 */}
            <div data-testid="progress-summary" style={{ display: "none" }}>
              <span data-testid="progress-total">
                投标人 {(sse.progress ?? progress)?.total_bidders ?? 0}
              </span>
              <span data-testid="progress-extracted">
                已解析 {(sse.progress ?? progress)?.extracted_count ?? 0}
              </span>
              <span data-testid="progress-extracting">
                解析中 {(sse.progress ?? progress)?.extracting_count ?? 0}
              </span>
              <span data-testid="progress-needs-password">
                需密码 {(sse.progress ?? progress)?.needs_password_count ?? 0}
              </span>
              <span data-testid="progress-failed">
                失败 {(sse.progress ?? progress)?.failed_count ?? 0}
              </span>
            </div>
          </div>
        )}
      </Card>

      {/* 招标文件(detect-tender-baseline §7) — feature flag 控制整组隐藏/显示 */}
      {tenderBaselineEnabled && (
        <div style={{ marginBottom: 16 }}>
          <TenderUploadCard
            projectId={projectId}
            onChanged={() => {
              if (project.status === "completed") {
                setShowRerunDialog(true);
              }
            }}
          />
        </div>
      )}

      {/* 投标人管理 */}
      <Card
        variant="outlined"
        data-testid="bidders-section"
        styles={{ body: { padding: 0 } }}
        style={{ marginBottom: 16 }}
      >
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid #f0f2f5",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <Space size={8} align="center">
            <Typography.Title level={5} style={{ margin: 0, fontWeight: 600 }}>
              投标人管理
            </Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {mergedBidders.length} 个
            </Typography.Text>
          </Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setShowAddBidder(true)}
            data-testid="open-add-bidder"
          >
            添加投标人
          </Button>
        </div>

        {mergedBidders.length === 0 ? (
          <div style={{ padding: "48px 0" }}>
            <Empty
              description={
                <span data-testid="bidders-empty" style={{ color: "#8a919d" }}>
                  还没有投标人,点击右上角添加第一个
                </span>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        ) : (
          <div>
            {mergedBidders.map((b, idx) => (
              <BidderRow
                key={b.id}
                bidder={b}
                isLast={idx === mergedBidders.length - 1}
                projectId={projectId}
                onOpenDrawer={() => setDrawerBidderId(b.id)}
                onRefresh={() => {
                  void reloadProject();
                  void reloadDocs(b.id);
                }}
                onDelete={() => onDeleteBidder(b.id, b.name)}
                onOpenDecrypt={() => {
                  const archive = (docsByBidder[b.id] ?? []).find(
                    (d) => d.parse_status === "needs_password",
                  );
                  if (archive) setDecryptTarget(archive);
                  else void reloadDocs(b.id);
                }}
              />
            ))}
          </div>
        )}
      </Card>

      {/* 报价规则 */}
      <Card
        variant="outlined"
        data-testid="price-section"
        styles={{ body: { padding: 20 } }}
      >
        <Typography.Title level={5} style={{ margin: "0 0 12px", fontWeight: 600 }}>
          报价规则
        </Typography.Title>
        <div style={{ marginBottom: 16 }}>
          <PriceConfigForm projectId={projectId} />
        </div>
        <div>
          <PriceRulesPanel projectId={projectId} />
        </div>
      </Card>

      {/* 投标人详情 Drawer */}
      <Drawer
        open={drawerBidderId !== null && drawerBidder !== null}
        onClose={() => setDrawerBidderId(null)}
        width={560}
        destroyOnHidden
        title={
          drawerBidder ? (
            <Space size={8}>
              <span style={{ fontSize: 15, fontWeight: 600 }}>
                {drawerBidder.name}
              </span>
              <Tag
                color={BIDDER_STATUS_COLORS[drawerBidder.parse_status] ?? "default"}
                style={{ margin: 0 }}
              >
                {BIDDER_STATUS_LABELS[drawerBidder.parse_status] ??
                  drawerBidder.parse_status}
              </Tag>
            </Space>
          ) : (
            "投标人详情"
          )
        }
      >
        {drawerBidder ? (
          <Space direction="vertical" size={20} style={{ width: "100%" }}>
            {/* honest-detection-results F3: 身份信息缺失提示 */}
            {drawerBidder.identity_info_status === "insufficient" && (
              <div
                style={{
                  padding: 12,
                  background: "#eef4fb",
                  border: "1px solid #bcd7f0",
                  borderRadius: 6,
                }}
                data-testid={`identity-info-missing-${drawerBidder.id}`}
              >
                <Space size={8} align="start">
                  <InfoCircleOutlined
                    style={{ color: "#1d4584", marginTop: 3 }}
                  />
                  <Typography.Text style={{ fontSize: 13 }}>
                    身份信息缺失:LLM 未能从投标文件中识别出投标人身份信息,
                    error_consistency 等依赖身份的维度已降级
                  </Typography.Text>
                </Space>
              </div>
            )}

            {/* 解密提示 */}
            {drawerBidder.parse_status === "needs_password" && (
              <div
                style={{
                  padding: 12,
                  background: "#fcf3e3",
                  border: "1px solid #f0e0b0",
                  borderRadius: 6,
                }}
              >
                <Space size={8}>
                  <LockOutlined style={{ color: "#c27c0e" }} />
                  <Typography.Text style={{ fontSize: 13 }}>
                    压缩包需要密码才能解压
                  </Typography.Text>
                  <Button
                    size="small"
                    type="primary"
                    data-testid={`open-decrypt-${drawerBidder.id}`}
                    onClick={() => {
                      const archive = (docsByBidder[drawerBidder.id] ?? []).find(
                        (d) => d.parse_status === "needs_password",
                      );
                      if (archive) setDecryptTarget(archive);
                      else void reloadDocs(drawerBidder.id);
                    }}
                  >
                    输入密码
                  </Button>
                </Space>
              </div>
            )}

            {/* 解析错误 */}
            {drawerBidder.parse_error && (
              <div
                style={{
                  padding: 12,
                  background: "#fdecec",
                  border: "1px solid #f5c0c0",
                  borderRadius: 6,
                  fontSize: 12,
                  color: "#c53030",
                }}
              >
                {drawerBidder.parse_error}
              </div>
            )}

            {/* 文件树 */}
            <div>
              <Typography.Text
                type="secondary"
                style={{
                  fontSize: 12,
                  letterSpacing: 0.3,
                  display: "block",
                  marginBottom: 10,
                }}
              >
                文件列表 · {drawerBidder.file_count} 个
              </Typography.Text>
              {docsByBidder[drawerBidder.id] ? (
                <FileTree
                  documents={docsByBidder[drawerBidder.id]}
                  onDocumentChanged={() => void reloadDocs(drawerBidder.id)}
                />
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  正在加载文件列表...
                </Typography.Text>
              )}
            </div>
          </Space>
        ) : null}
      </Drawer>

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
      {tenderBaselineEnabled && (
        <RerunAfterTenderDialog
          open={showRerunDialog}
          loading={rerunLoading}
          onCancel={() => setShowRerunDialog(false)}
          onConfirm={async () => {
            setRerunLoading(true);
            try {
              await api.startAnalysis(projectId);
              await detect.refetch();
              await reloadProject();
              void message.success("已基于新基线重新启动检测");
              setShowRerunDialog(false);
            } catch (err) {
              if (err instanceof ApiError && err.status === 409) {
                void message.info("已在检测中,进度面板已展开");
                setShowRerunDialog(false);
              } else if (err instanceof ApiError) {
                void message.error(`启动失败 (${err.status})`);
              } else {
                void message.error("启动失败,请稍后重试");
              }
            } finally {
              setRerunLoading(false);
            }
          }}
        />
      )}
    </div>
  );
}

/* ───────── 子组件 ───────── */

function MetaChip({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 13,
      }}
    >
      <span style={{ color: "#8a919d", fontSize: 13 }}>{icon}</span>
      <span style={{ color: "#8a919d" }}>{label}</span>
      <span style={{ color: "#1f2328", fontWeight: 500 }}>{value}</span>
    </span>
  );
}

/**
 * Hero 区的检测主按钮组件
 * 复用 StartDetectButton(含前置校验 tooltip)
 */
function HeroDetectArea({
  projectId,
  project,
  bidders,
  detect,
  onReloadProject,
  onGoReport,
}: {
  projectId: number;
  project: ProjectDetail;
  bidders: Bidder[];
  /**
   * fix-bug-triple-and-direction-high P7:detect 实例从父组件 ProjectDetailPage 传入
   * (lift hook),让 Tag 渲染处能拿到 detect.projectStatus 实时同步。
   */
  detect: ReturnType<typeof useDetectProgress>;
  onReloadProject: () => void;
  onGoReport: (version: number) => void;
}) {
  // 刚点"启动检测",SSE 事件还没到时撑开占位面板
  const [justStarted, setJustStarted] = useState(false);

  // 兜底 1:收到 agent_tasks 即自动清掉 justStarted(正常场景立即切到 running)
  useEffect(() => {
    if (justStarted && detect.agentTasks.length > 0) {
      setJustStarted(false);
    }
  }, [justStarted, detect.agentTasks.length]);

  // 兜底 2:15s 内没拿到 agent_tasks → 自动清 justStarted,fall through 到常规逻辑
  // 防止 token 过期/SSE 断线下"初始化..."永久卡住
  useEffect(() => {
    if (!justStarted) return;
    const t = window.setTimeout(() => setJustStarted(false), 15_000);
    return () => window.clearTimeout(t);
  }, [justStarted]);

  const hasStarted =
    detect.version !== null ||
    project.status === "analyzing" ||
    project.status === "completed" ||
    justStarted;

  return (
    <div data-testid="detect-section">
      <StartDetectButton
        projectId={projectId}
        projectStatus={detect.projectStatus ?? project.status}
        // 用实时 bidders(SSE 合并后),避免 project.bidders 过期导致按钮误禁用
        bidders={bidders.map((b) => ({
          id: b.id,
          name: b.name,
          parse_status: b.parse_status,
          file_count: b.file_count,
          identity_info_status: b.identity_info_status,
        }))}
        onStarted={() => {
          // 立即乐观反馈 + 主动拉状态 + 刷新项目(status→analyzing)
          setJustStarted(true);
          void detect.refetch();
          onReloadProject();
          // 之后 agentTasks 到了 justStarted 不影响渲染(有真实数据就走 running/completed 分支)
        }}
      />
      {hasStarted && (
        <div style={{ marginTop: 12, width: "100%", maxWidth: 520 }}>
          <DetectProgressIndicator
            agentTasks={detect.agentTasks}
            connected={detect.connected}
            lastEventAt={detect.lastEventAt}
            latestReport={detect.latestReport}
            fallbackVersion={detect.version ?? 1}
            justStarted={justStarted}
            onViewReport={onGoReport}
          />
        </div>
      )}
    </div>
  );
}

/**
 * 投标人行:紧凑列表,点击打开 Drawer;按钮点击 stopPropagation
 */
function BidderRow({
  bidder: b,
  isLast,
  projectId,
  onOpenDrawer,
  onRefresh,
  onDelete,
  onOpenDecrypt,
}: {
  bidder: Bidder;
  isLast: boolean;
  projectId: number;
  onOpenDrawer: () => void;
  onRefresh: () => void;
  onDelete: () => void;
  onOpenDecrypt: () => void;
}) {
  return (
    <div
      data-testid={`bidder-card-${b.id}`}
      onClick={onOpenDrawer}
      style={{
        padding: "14px 20px",
        borderBottom: isLast ? "none" : "1px solid #f0f2f5",
        display: "flex",
        alignItems: "center",
        gap: 12,
        cursor: "pointer",
        transition: "background-color 0.15s ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "#f7f9fc";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "";
      }}
    >
      <FileTextOutlined style={{ color: "#8a919d", fontSize: 18, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Typography.Text
          strong
          data-testid={`bidder-name-${b.id}`}
          style={{
            fontSize: 14,
            minWidth: 0,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {b.name}
        </Typography.Text>
        <Tag
          color={BIDDER_STATUS_COLORS[b.parse_status] ?? "default"}
          data-testid={`bidder-status-${b.id}`}
          style={{ margin: 0 }}
        >
          {BIDDER_STATUS_LABELS[b.parse_status] ?? b.parse_status}
        </Tag>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {b.file_count} 个文件
        </Typography.Text>
      </div>

      {/* 右侧操作区(stopPropagation 避免冒泡打开 Drawer) */}
      <div
        style={{ display: "flex", gap: 4, alignItems: "center", flexShrink: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        {b.parse_status === "needs_password" && (
          <Tooltip title="输入密码解密">
            <Button
              size="small"
              type="text"
              icon={<LockOutlined />}
              style={{ color: "#c27c0e" }}
              onClick={onOpenDecrypt}
              aria-label="输入密码"
            />
          </Tooltip>
        )}
        <UploadButton
          projectId={projectId}
          bidderId={b.id}
          onUploaded={onRefresh}
        />
        <Tooltip title="刷新文件列表">
          <Button
            size="small"
            type="text"
            icon={<ReloadOutlined />}
            onClick={onRefresh}
            data-testid={`bidder-refresh-${b.id}`}
            aria-label="刷新"
          />
        </Tooltip>
        <Tooltip title="删除投标人">
          <Button
            size="small"
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={onDelete}
            data-testid={`bidder-delete-${b.id}`}
            aria-label="删除"
          />
        </Tooltip>
        <RightOutlined style={{ color: "#b1b6bf", fontSize: 10, marginLeft: 2 }} />
      </div>
    </div>
  );
}

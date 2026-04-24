/**
 * 项目列表页 (C3 project-mgmt, US-2.2)
 *
 * Dify 式卡片网格重设计:
 *  - 无标题 banner(左栏已标识"项目",Tab 即是页头)
 *  - 第一张卡永远是"+ 新建项目"特殊卡(虚线边,dashed)
 *  - 其余卡:状态 icon + 名称 + 编号 + 描述/限价 + Tag + 底部(时间 · 查看 · 删)
 *  - 图标按 status 切(draft/parsing/ready/analyzing/completed 5 种)
 *  - 固定高 204px;gap 16px;响应式 4/3/2/1 列
 *  - hover:边框深蓝 + 阴影加深
 *
 * 业务契约 0 变动,所有 testid 保留。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  App,
  Button,
  Col,
  Input,
  Row,
  Select,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  FileProtectOutlined,
  PlusOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { ApiError, api } from "../../services/api";
import type { ProjectListItem, ProjectListResponse } from "../../types";

const PAGE_SIZE = 20;

const TAB_TO_STATUSES: Record<string, string[]> = {
  active: ["draft", "parsing", "ready", "analyzing"],
  completed: ["completed"],
  all: [],
};

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

const RISK_LABELS: Record<string, string> = {
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

const RISK_COLORS: Record<string, string> = {
  high: "error",
  medium: "warning",
  low: "success",
};

/**
 * 项目图标 —— 按项目名哈希生成色块 + 首字
 * (Dify / 飞书 / 钉钉同款"项目头像",克制不 AI 味)
 *
 * 8 色商务调色盘(克制饱和度,避开霓虹/紫粉)
 */
const ICON_PALETTE = [
  "#1d4584", // 品牌深蓝
  "#2d7a4a", // 墨绿
  "#c27c0e", // 琥珀
  "#883a6d", // 酒红
  "#5a57a3", // 靛青
  "#aa6c39", // 铜
  "#277c8c", // 青灰
  "#a65375", // 豆沙红
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function getProjectIconColor(name: string): string {
  if (!name) return ICON_PALETTE[0];
  return ICON_PALETTE[hashString(name) % ICON_PALETTE.length];
}

function getProjectIconChar(name: string): string {
  const s = (name ?? "").trim();
  if (!s) return "项";
  // 取第一个非空白字符(兼容 emoji / 多字节字符)
  const match = s.match(/\S/);
  return match ? match[0] : "项";
}

function timeAgo(iso: string): string {
  const now = Date.now();
  const t = new Date(iso).getTime();
  const diff = Math.max(0, now - t);
  const day = 24 * 60 * 60 * 1000;
  if (diff < 60 * 1000) return "刚刚";
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / (60 * 1000))} 分钟前`;
  if (diff < day) return `${Math.floor(diff / (60 * 60 * 1000))} 小时前`;
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`;
  return new Date(iso).toLocaleDateString();
}

export default function ProjectListPage() {
  const { modal, message } = App.useApp();

  const [tab, setTab] = useState<"active" | "completed" | "all">("active");
  const [items, setItems] = useState<ProjectListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [submittedSearch, setSubmittedSearch] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tabTotals, setTabTotals] = useState({ active: 0, completed: 0, all: 0 });

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const statuses = TAB_TO_STATUSES[tab] ?? [];
      const queryStatus =
        statusFilter || (statuses.length === 1 ? statuses[0] : undefined);

      const res: ProjectListResponse = await api.listProjects({
        page,
        size: PAGE_SIZE,
        status: queryStatus,
        risk_level: riskFilter || undefined,
        search: submittedSearch || undefined,
      });

      let finalItems = res.items;
      let finalTotal = res.total;
      if (tab === "active" && !statusFilter) {
        finalItems = res.items.filter((p) => statuses.includes(p.status));
        finalTotal = finalItems.length < PAGE_SIZE ? finalItems.length : res.total;
      }
      setItems(finalItems);
      setTotal(finalTotal);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`加载失败 (${err.status})`);
      } else {
        setError("加载失败,请稍后重试");
      }
    } finally {
      setIsLoading(false);
    }
  }, [tab, page, statusFilter, riskFilter, submittedSearch]);

  const loadTabTotals = useCallback(async () => {
    try {
      const [allRes, completedRes] = await Promise.all([
        api.listProjects({ page: 1, size: 1 }),
        api.listProjects({ page: 1, size: 1, status: "completed" }),
      ]);
      setTabTotals({
        active: Math.max(0, allRes.total - completedRes.total),
        completed: completedRes.total,
        all: allRes.total,
      });
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadTabTotals();
  }, [loadTabTotals]);

  function onDelete(p: ProjectListItem) {
    modal.confirm({
      title: "删除项目",
      content: (
        <span>
          确定删除项目 <b>{p.name}</b>?该操作会隐藏项目(软删除,可由管理员恢复)。
        </span>
      ),
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      async onOk() {
        try {
          await api.deleteProject(p.id);
          void message.success("删除成功");
          void load();
          void loadTabTotals();
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            void message.error("检测进行中,无法删除");
          } else if (err instanceof ApiError) {
            void message.error(`删除失败 (${err.status})`);
          } else {
            void message.error("删除失败,请稍后重试");
          }
        }
      },
    });
  }

  const hasFilters =
    !!statusFilter || !!riskFilter || !!submittedSearch || tab !== "active";
  const isReallyEmpty = items.length === 0 && !hasFilters;

  const tabItems = useMemo(
    () => [
      {
        key: "active",
        label: (
          <TabLabel text="进行中" count={tabTotals.active} active={tab === "active"} />
        ),
      },
      {
        key: "completed",
        label: (
          <TabLabel text="已完成" count={tabTotals.completed} active={tab === "completed"} />
        ),
      },
      {
        key: "all",
        label: <TabLabel text="全部" count={tabTotals.all} active={tab === "all"} />,
      },
    ],
    [tab, tabTotals],
  );

  return (
    <div>
      {/* Tab 行即页头,左 Tab 右筛选,无单独标题 banner */}
      <Tabs
        activeKey={tab}
        onChange={(k) => {
          setTab(k as "active" | "completed" | "all");
          setPage(1);
          setStatusFilter("");
          setRiskFilter("");
        }}
        tabBarStyle={{
          margin: "0 0 20px",
          padding: "0 4px",
          borderBottom: "1px solid #e4e7ed",
        }}
        tabBarExtraContent={{
          right: (
            <div
              style={{
                display: "flex",
                gap: 4,
                alignItems: "center",
              }}
            >
              <div data-testid="filter-status">
                <Select
                  value={statusFilter}
                  onChange={(v) => {
                    setPage(1);
                    setStatusFilter(v);
                  }}
                  style={{ width: 114 }}
                  variant="borderless"
                  options={[
                    { value: "", label: "全部状态" },
                    ...Object.entries(STATUS_LABELS).map(([v, label]) => ({
                      value: v,
                      label,
                    })),
                  ]}
                />
              </div>
              <div
                aria-hidden="true"
                style={{ width: 1, height: 14, background: "#e4e7ed" }}
              />
              <div data-testid="filter-risk">
                <Select
                  value={riskFilter}
                  onChange={(v) => {
                    setPage(1);
                    setRiskFilter(v);
                  }}
                  style={{ width: 114 }}
                  variant="borderless"
                  options={[
                    { value: "", label: "全部风险" },
                    ...Object.entries(RISK_LABELS).map(([v, label]) => ({
                      value: v,
                      label,
                    })),
                  ]}
                />
              </div>
              <div data-testid="search-input" style={{ width: 240, marginLeft: 8 }}>
                <Input.Search
                  placeholder="按名称 / 招标编号搜索"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onSearch={(v) => {
                    setPage(1);
                    setSubmittedSearch(v.trim());
                  }}
                  enterButton={<span data-testid="search-submit">搜索</span>}
                  allowClear
                />
              </div>
            </div>
          ),
        }}
        items={tabItems}
      />

      {error ? (
        <div data-testid="list-error" style={{ color: "#c53030", marginBottom: 16 }}>
          {error}
        </div>
      ) : null}

      {/* 列表主体 */}
      {isReallyEmpty && !isLoading ? (
        <EmptyPlaceholder />
      ) : items.length === 0 && hasFilters && !isLoading ? (
        <FilterEmptyPlaceholder />
      ) : (
        <div data-testid={items.length > 0 && !isLoading ? "project-grid" : undefined}>
          <Row gutter={[16, 16]}>
            {/* 第一张卡:新建项目 */}
            <Col xs={24} sm={12} md={8} xl={6}>
              <CreateProjectCard />
            </Col>
            {items.map((p) => (
              <Col key={p.id} xs={24} sm={12} md={8} xl={6}>
                <ProjectCard project={p} onDelete={onDelete} />
              </Col>
            ))}
            {/* 加载骨架占位(仅首次加载时显示 3 张骨架) */}
            {isLoading &&
              items.length === 0 &&
              Array.from({ length: 3 }).map((_, i) => (
                <Col key={`skeleton-${i}`} xs={24} sm={12} md={8} xl={6}>
                  <SkeletonCard />
                </Col>
              ))}
          </Row>
        </div>
      )}

      {/* 分页:仅 total > PAGE_SIZE 时显示 */}
      {total > PAGE_SIZE && (
        <div
          data-testid="pagination"
          style={{
            marginTop: 24,
            display: "flex",
            justifyContent: "center",
            gap: 8,
            alignItems: "center",
          }}
        >
          <Button
            data-testid="page-prev"
            size="small"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12, margin: "0 8px" }}
            data-testid="page-info"
          >
            {page} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}
          </Typography.Text>
          <Button
            data-testid="page-next"
            size="small"
            disabled={page >= Math.ceil(total / PAGE_SIZE)}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}

/* ───────── 子组件 ───────── */

function TabLabel({ text, count, active }: { text: string; count: number; active: boolean }) {
  return (
    <span style={{ fontSize: 14, display: "inline-flex", alignItems: "center", gap: 6 }}>
      {text}
      <span
        style={{
          fontSize: 11,
          padding: "0 7px",
          height: 18,
          lineHeight: "18px",
          borderRadius: 9,
          background: active ? "#eef3fb" : "#f0f2f5",
          color: active ? "#1d4584" : "#8a919d",
          fontWeight: 500,
          minWidth: 20,
          textAlign: "center",
        }}
      >
        {count}
      </span>
    </span>
  );
}

function CreateProjectCard() {
  return (
    <Link
      to="/projects/new"
      data-testid="new-project-btn"
      className="project-card project-card--create"
      style={{ textDecoration: "none" }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          background: "#eef3fb",
          color: "#1d4584",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 20,
          marginBottom: 12,
        }}
      >
        <PlusOutlined />
      </div>
      <Typography.Text
        strong
        style={{ fontSize: 15, color: "#1f2328", marginBottom: 4 }}
      >
        新建项目
      </Typography.Text>
      <Typography.Text
        type="secondary"
        style={{ fontSize: 12.5, textAlign: "center", lineHeight: 1.6 }}
      >
        创建新的围标检测项目
        <br />
        上传投标文件并启动检测
      </Typography.Text>
    </Link>
  );
}

function ProjectCard({
  project: p,
  onDelete,
}: {
  project: ProjectListItem;
  onDelete: (p: ProjectListItem) => void;
}) {
  const iconColor = getProjectIconColor(p.name);
  const iconChar = getProjectIconChar(p.name);
  const hasDescription = p.description && p.description.trim().length > 0;

  return (
    <Link
      to={`/projects/${p.id}`}
      data-testid={`project-card-${p.id}`}
      className="project-card"
      style={{ textDecoration: "none" }}
    >
      {/* 顶部:项目头像(按名字哈希配色 + 首字) */}
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          background: iconColor,
          color: "#ffffff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 18,
          fontWeight: 600,
          flexShrink: 0,
          marginBottom: 12,
          letterSpacing: 0,
        }}
        aria-hidden="true"
      >
        {iconChar}
      </div>

      {/* 名称(纯 CSS ellipsis,避开 antd Typography 在 flex 容器里的测量 bug) */}
      <div
        title={p.name}
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: "#1f2328",
          lineHeight: 1.4,
          marginBottom: 2,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          width: "100%",
        }}
      >
        {p.name}
      </div>

      {/* 编号 */}
      <div
        style={{
          fontSize: 12,
          fontFamily: "monospace",
          color: "#8a919d",
          marginBottom: 10,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          width: "100%",
        }}
      >
        {p.bid_code ?? "— 未填编号"}
      </div>

      {/* 描述 / 限价(若无则留空位维持对齐) */}
      <div style={{ flex: 1, minHeight: 36, marginBottom: 10 }}>
        {hasDescription ? (
          <div
            style={{
              fontSize: 12.5,
              color: "#5c6370",
              lineHeight: 1.6,
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {p.description}
          </div>
        ) : p.max_price ? (
          <div style={{ fontSize: 12.5, color: "#5c6370" }}>
            最高限价:<b style={{ color: "#1f2328" }}>{formatPrice(p.max_price)}</b>
          </div>
        ) : null}
      </div>

      {/* 状态 + 风险 Tag 行 */}
      <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
        <Tag color={STATUS_COLORS[p.status] ?? "default"} style={{ margin: 0 }}>
          {STATUS_LABELS[p.status] ?? p.status}
        </Tag>
        {p.risk_level ? (
          <Tag color={RISK_COLORS[p.risk_level] ?? "default"} style={{ margin: 0 }}>
            {RISK_LABELS[p.risk_level] ?? p.risk_level}
          </Tag>
        ) : (
          <Tag style={{ margin: 0 }}>未检测</Tag>
        )}
      </div>

      {/* 底部分隔 + meta + 操作 */}
      <div
        style={{
          borderTop: "1px solid #f0f2f5",
          paddingTop: 10,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: "auto",
        }}
      >
        <Tooltip title={new Date(p.created_at).toLocaleString()}>
          <Typography.Text
            type="secondary"
            style={{ fontSize: 11.5, letterSpacing: 0.2 }}
          >
            <FileProtectOutlined style={{ marginRight: 4, fontSize: 11 }} />
            {timeAgo(p.created_at)}
          </Typography.Text>
        </Tooltip>
        <div style={{ display: "flex", gap: 2 }}>
          <Tooltip title="删除项目">
            <Button
              size="small"
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onDelete(p);
              }}
              data-testid={`project-delete-${p.id}`}
              aria-label="删除"
              style={{ height: 26, width: 26, padding: 0 }}
            />
          </Tooltip>
          <span
            data-testid={`project-open-${p.id}`}
            style={{
              fontSize: 12,
              color: "#1d4584",
              display: "inline-flex",
              alignItems: "center",
              gap: 2,
              padding: "0 6px",
              fontWeight: 500,
            }}
          >
            查看 <RightOutlined style={{ fontSize: 9 }} />
          </span>
        </div>
      </div>
    </Link>
  );
}

function SkeletonCard() {
  return (
    <div
      className="project-card"
      aria-hidden="true"
      style={{ cursor: "default", pointerEvents: "none", opacity: 0.6 }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          background: "#f0f2f5",
          marginBottom: 12,
        }}
      />
      <div
        style={{
          height: 18,
          background: "#f0f2f5",
          borderRadius: 4,
          marginBottom: 6,
          width: "80%",
        }}
      />
      <div
        style={{
          height: 12,
          background: "#f5f7fa",
          borderRadius: 4,
          marginBottom: 14,
          width: "50%",
        }}
      />
      <div
        style={{
          flex: 1,
          height: 36,
          background: "#fafbfc",
          borderRadius: 4,
          marginBottom: 10,
        }}
      />
    </div>
  );
}

function EmptyPlaceholder() {
  return (
    <div
      data-testid="empty-state"
      style={{
        padding: "60px 20px",
        textAlign: "center",
        background: "#ffffff",
        border: "1px solid #e4e7ed",
        borderRadius: 10,
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          margin: "0 auto 20px",
          borderRadius: 14,
          background: "#eef3fb",
          color: "#1d4584",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 28,
        }}
      >
        <FileProtectOutlined />
      </div>
      <Typography.Title level={4} style={{ margin: "0 0 6px", fontWeight: 600 }}>
        还没有项目
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: "0 0 20px", fontSize: 13 }}>
        创建项目后,可添加投标人、上传文件并启动围标检测
      </Typography.Paragraph>
      <Link to="/projects/new">
        <Button type="primary" size="large" icon={<PlusOutlined />}>
          新建项目
        </Button>
      </Link>
    </div>
  );
}

function FilterEmptyPlaceholder() {
  return (
    <div
      style={{
        padding: "48px 20px",
        textAlign: "center",
        background: "#ffffff",
        border: "1px solid #e4e7ed",
        borderRadius: 10,
      }}
    >
      <Typography.Text type="secondary" style={{ fontSize: 13 }}>
        未找到匹配的项目,请调整筛选条件
      </Typography.Text>
    </div>
  );
}

function formatPrice(raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)} 万`;
  return n.toLocaleString("zh-CN");
}

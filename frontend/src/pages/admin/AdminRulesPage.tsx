/**
 * 规则配置页 (C17 admin-rules, US-9.1)
 *
 * 视觉重设:
 *  - Breadcrumb + 标题 + 副标题
 *  - 维度配置:每维度一张 Card(enabled Switch / 权重 InputNumber / LLM Switch / 特有阈值)
 *  - 全局配置:独立 Card,Descriptions 风格分组
 *  - 底部操作条:保存(主)+ 恢复默认(次)
 *
 * 契约 0 变动:所有 data-testid 原样保留
 *   - error-msg / success-msg / dimensions-section / dim-<name> / dim-<name>-enabled
 *   - dim-<name>-weight / dim-<name>-llm / dim-<name>-<threshold>
 *   - global-section / risk-high / risk-medium / metadata-whitelist / hardware-keywords
 *   - min-paragraph-length / file-retention-days / save-btn / restore-btn
 */
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  App,
  Breadcrumb,
  Button,
  Card,
  Col,
  InputNumber,
  Row,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import { SaveOutlined, UndoOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../services/api";
import type { RulesConfig } from "../../types";

const DIM_LABELS: Record<string, string> = {
  hardware_fingerprint: "硬件指纹",
  error_consistency: "错误一致性",
  text_similarity: "文本相似度",
  price_similarity: "报价相似度",
  image_reuse: "图片复用",
  language_style: "语言风格",
  software_metadata: "软件元数据",
  pricing_pattern: "报价模式",
  price_ceiling: "报价天花板",
  operation_time: "操作时间",
};

const THRESHOLD_LABELS: Record<string, string> = {
  threshold: "阈值",
  phash_distance: "pHash 距离",
  group_threshold: "分组阈值",
  r_squared_threshold: "R² 阈值",
  variance_threshold: "方差阈值",
  range_min: "范围最小值",
  range_max: "范围最大值",
  window_minutes: "时间窗口(分钟)",
  min_bidders: "最少投标人数",
};

const KNOWN_FIELDS = new Set(["enabled", "weight", "llm_enabled"]);

export default function AdminRulesPage() {
  const { message } = App.useApp();
  const [config, setConfig] = useState<RulesConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getRules();
      setConfig(res.config);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载规则失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  function updateDim(dimName: string, field: string, value: unknown) {
    if (!config) return;
    setConfig({
      ...config,
      dimensions: {
        ...config.dimensions,
        [dimName]: { ...config.dimensions[dimName], [field]: value },
      },
    });
    setSuccess("");
  }

  function updateGlobal<K extends keyof RulesConfig>(
    key: K,
    value: RulesConfig[K],
  ) {
    if (!config) return;
    setConfig({ ...config, [key]: value });
    setSuccess("");
  }

  async function handleSave() {
    if (!config) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await api.updateRules(config);
      setConfig(res.config);
      setSuccess("保存成功");
      void message.success("保存成功");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleRestore() {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await api.updateRules({ restore_defaults: true });
      setConfig(res.config);
      setSuccess("已恢复默认配置");
      void message.success("已恢复默认配置");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "恢复默认失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: "center" }}>
        <Spin tip="加载中..." />
      </div>
    );
  }
  if (!config) return <p>无法加载配置</p>;

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">首页</Link> },
          { title: "管理" },
          { title: "规则配置" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 20,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <Typography.Title level={3} style={{ margin: 0, fontWeight: 600 }}>
            规则配置
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
            调整 10 维度开关、权重和阈值,以及全局参数
          </Typography.Paragraph>
        </div>
        <Space>
          <Button
            icon={<UndoOutlined />}
            onClick={handleRestore}
            disabled={saving}
            data-testid="restore-btn"
          >
            恢复默认
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            data-testid="save-btn"
          >
            保存
          </Button>
        </Space>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          data-testid="error-msg"
          showIcon
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 16 }}
        />
      )}
      {success && (
        <Alert
          type="success"
          message={success}
          data-testid="success-msg"
          showIcon
          closable
          onClose={() => setSuccess("")}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 维度配置 */}
      <Typography.Title level={5} style={{ fontWeight: 600, margin: "8px 0 12px" }}>
        维度配置
      </Typography.Title>
      <div data-testid="dimensions-section">
        <Row gutter={[12, 12]}>
          {Object.entries(config.dimensions).map(([dimName, dimCfg]) => (
            <Col key={dimName} xs={24} lg={12}>
              <Card
                variant="outlined"
                data-testid={`dim-${dimName}`}
                styles={{ body: { padding: 16 } }}
                title={
                  <Space size={10}>
                    <span style={{ fontWeight: 600 }}>
                      {DIM_LABELS[dimName] || dimName}
                    </span>
                    <Typography.Text
                      type="secondary"
                      style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 400 }}
                    >
                      {dimName}
                    </Typography.Text>
                  </Space>
                }
                extra={
                  <Switch
                    checked={dimCfg.enabled}
                    onChange={(v) => updateDim(dimName, "enabled", v)}
                    data-testid={`dim-${dimName}-enabled`}
                    size="small"
                  />
                }
              >
                <Space wrap size={[24, 12]} style={{ width: "100%" }}>
                  {dimCfg.weight !== undefined && (
                    <span>
                      <Typography.Text
                        type="secondary"
                        style={{ fontSize: 12, marginRight: 6 }}
                      >
                        权重
                      </Typography.Text>
                      <InputNumber
                        value={dimCfg.weight}
                        min={0}
                        step={1}
                        size="small"
                        onChange={(v) => updateDim(dimName, "weight", Number(v))}
                        data-testid={`dim-${dimName}-weight`}
                        style={{ width: 76 }}
                      />
                    </span>
                  )}
                  {dimCfg.llm_enabled !== undefined && (
                    <span>
                      <Typography.Text
                        type="secondary"
                        style={{ fontSize: 12, marginRight: 6 }}
                      >
                        LLM
                      </Typography.Text>
                      <Switch
                        checked={dimCfg.llm_enabled}
                        onChange={(v) => updateDim(dimName, "llm_enabled", v)}
                        data-testid={`dim-${dimName}-llm`}
                        size="small"
                      />
                    </span>
                  )}
                  {Object.entries(dimCfg)
                    .filter(([k]) => !KNOWN_FIELDS.has(k))
                    .map(([k, v]) => (
                      <span key={k}>
                        <Typography.Text
                          type="secondary"
                          style={{ fontSize: 12, marginRight: 6 }}
                        >
                          {THRESHOLD_LABELS[k] || k}
                        </Typography.Text>
                        <InputNumber
                          value={(v as number) ?? undefined}
                          step="any"
                          size="small"
                          onChange={(val) =>
                            updateDim(dimName, k, Number(val))
                          }
                          data-testid={`dim-${dimName}-${k}`}
                          style={{ width: 96 }}
                        />
                      </span>
                    ))}
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </div>

      {/* 全局配置 */}
      <Typography.Title level={5} style={{ fontWeight: 600, margin: "24px 0 12px" }}>
        全局配置
      </Typography.Title>
      <Card
        variant="outlined"
        data-testid="global-section"
        styles={{ body: { padding: 20 } }}
      >
        <Space direction="vertical" size={20} style={{ width: "100%" }}>
          <div>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, letterSpacing: 0.3, display: "block", marginBottom: 8 }}
            >
              风险等级阈值
            </Typography.Text>
            <Space size={20} wrap>
              <span>
                <span style={{ fontSize: 13, marginRight: 6 }}>高风险 ≥</span>
                <InputNumber
                  value={config.risk_levels.high}
                  min={1}
                  max={100}
                  size="middle"
                  onChange={(v) =>
                    updateGlobal("risk_levels", {
                      ...config.risk_levels,
                      high: Number(v),
                    })
                  }
                  data-testid="risk-high"
                  style={{ width: 80 }}
                />
              </span>
              <span>
                <span style={{ fontSize: 13, marginRight: 6 }}>中风险 ≥</span>
                <InputNumber
                  value={config.risk_levels.medium}
                  min={1}
                  max={100}
                  size="middle"
                  onChange={(v) =>
                    updateGlobal("risk_levels", {
                      ...config.risk_levels,
                      medium: Number(v),
                    })
                  }
                  data-testid="risk-medium"
                  style={{ width: 80 }}
                />
              </span>
            </Space>
          </div>

          <div>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, letterSpacing: 0.3, display: "block", marginBottom: 8 }}
            >
              元数据白名单(每行一个)
            </Typography.Text>
            <textarea
              data-testid="metadata-whitelist"
              value={config.metadata_whitelist.join("\n")}
              onChange={(e) =>
                updateGlobal(
                  "metadata_whitelist",
                  e.target.value.split("\n").filter(Boolean),
                )
              }
              rows={4}
              style={{
                display: "block",
                width: "100%",
                padding: "8px 11px",
                border: "1px solid #e4e7ed",
                borderRadius: 6,
                fontFamily: "monospace",
                fontSize: 12.5,
                resize: "vertical",
                color: "#1f2328",
                outline: "none",
              }}
            />
          </div>

          <div>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, letterSpacing: 0.3, display: "block", marginBottom: 8 }}
            >
              硬件关键词(每行一个)
            </Typography.Text>
            <textarea
              data-testid="hardware-keywords"
              value={config.hardware_keywords.join("\n")}
              onChange={(e) =>
                updateGlobal(
                  "hardware_keywords",
                  e.target.value.split("\n").filter(Boolean),
                )
              }
              rows={3}
              style={{
                display: "block",
                width: "100%",
                padding: "8px 11px",
                border: "1px solid #e4e7ed",
                borderRadius: 6,
                fontFamily: "monospace",
                fontSize: 12.5,
                resize: "vertical",
                color: "#1f2328",
                outline: "none",
              }}
            />
          </div>

          <div>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, letterSpacing: 0.3, display: "block", marginBottom: 8 }}
            >
              其他参数
            </Typography.Text>
            <Space size={20} wrap>
              <span>
                <span style={{ fontSize: 13, marginRight: 6 }}>短段落过滤阈值</span>
                <InputNumber
                  value={config.min_paragraph_length}
                  min={1}
                  size="middle"
                  onChange={(v) =>
                    updateGlobal("min_paragraph_length", Number(v))
                  }
                  data-testid="min-paragraph-length"
                  style={{ width: 80 }}
                />
              </span>
              <span>
                <span style={{ fontSize: 13, marginRight: 6 }}>文件保留(天)</span>
                <InputNumber
                  value={config.file_retention_days}
                  min={1}
                  size="middle"
                  onChange={(v) =>
                    updateGlobal("file_retention_days", Number(v))
                  }
                  data-testid="file-retention-days"
                  style={{ width: 80 }}
                />
              </span>
            </Space>
          </div>
        </Space>
      </Card>
    </div>
  );
}

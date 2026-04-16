/**
 * 规则配置页 (C17 admin-users, US-9.1)
 *
 * 最简表单（不按维度分 Tab）：
 * - 10 维度各一组字段（enabled / weight / llm_enabled / 特有阈值）
 * - 全局配置区（risk_levels / keywords / whitelist / retention）
 * - 保存 + 恢复默认
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../services/api";
import type { RulesConfig } from "../../types";

/** 维度显示名称 */
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

/** 维度特有阈值字段的显示名 */
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
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "恢复默认失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p style={{ padding: 32 }}>加载中...</p>;
  if (!config) return <p style={{ padding: 32 }}>无法加载配置</p>;

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <h1 style={{ fontSize: 24, margin: 0 }}>规则配置</h1>
        <nav style={{ display: "flex", gap: 12 }}>
          <Link to="/admin/users">用户管理</Link>
          <Link to="/projects">返回项目</Link>
        </nav>
      </header>

      {error && (
        <div data-testid="error-msg" style={{ color: "red", marginBottom: 16 }}>
          {error}
        </div>
      )}
      {success && (
        <div
          data-testid="success-msg"
          style={{ color: "#2ecc71", marginBottom: 16 }}
        >
          {success}
        </div>
      )}

      {/* 维度配置 */}
      <h2 style={{ fontSize: 18, marginBottom: 12 }}>维度配置</h2>
      <div data-testid="dimensions-section">
        {Object.entries(config.dimensions).map(([dimName, dimCfg]) => (
          <fieldset
            key={dimName}
            data-testid={`dim-${dimName}`}
            style={{
              marginBottom: 16,
              padding: 12,
              border: "1px solid #ddd",
              borderRadius: 4,
            }}
          >
            <legend style={{ fontWeight: 600 }}>
              {DIM_LABELS[dimName] || dimName}
            </legend>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              <label>
                <input
                  type="checkbox"
                  data-testid={`dim-${dimName}-enabled`}
                  checked={dimCfg.enabled}
                  onChange={(e) =>
                    updateDim(dimName, "enabled", e.target.checked)
                  }
                />{" "}
                启用
              </label>
              {dimCfg.weight !== undefined && (
                <label>
                  权重：
                  <input
                    type="number"
                    data-testid={`dim-${dimName}-weight`}
                    value={dimCfg.weight}
                    min={0}
                    step={1}
                    onChange={(e) =>
                      updateDim(dimName, "weight", Number(e.target.value))
                    }
                    style={{ width: 60, marginLeft: 4 }}
                  />
                </label>
              )}
              {dimCfg.llm_enabled !== undefined && (
                <label>
                  <input
                    type="checkbox"
                    data-testid={`dim-${dimName}-llm`}
                    checked={dimCfg.llm_enabled}
                    onChange={(e) =>
                      updateDim(dimName, "llm_enabled", e.target.checked)
                    }
                  />{" "}
                  LLM
                </label>
              )}
              {/* 维度特有阈值 */}
              {Object.entries(dimCfg)
                .filter(([k]) => !KNOWN_FIELDS.has(k))
                .map(([k, v]) => (
                  <label key={k}>
                    {THRESHOLD_LABELS[k] || k}：
                    <input
                      type="number"
                      data-testid={`dim-${dimName}-${k}`}
                      value={(v as number) ?? ""}
                      step="any"
                      onChange={(e) =>
                        updateDim(dimName, k, Number(e.target.value))
                      }
                      style={{ width: 80, marginLeft: 4 }}
                    />
                  </label>
                ))}
            </div>
          </fieldset>
        ))}
      </div>

      {/* 全局配置 */}
      <h2 style={{ fontSize: 18, marginTop: 24, marginBottom: 12 }}>
        全局配置
      </h2>
      <div
        data-testid="global-section"
        style={{
          padding: 16,
          border: "1px solid #ddd",
          borderRadius: 4,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", gap: 16 }}>
          <label>
            高风险阈值（&ge;）：
            <input
              type="number"
              data-testid="risk-high"
              value={config.risk_levels.high}
              min={1}
              max={100}
              onChange={(e) =>
                updateGlobal("risk_levels", {
                  ...config.risk_levels,
                  high: Number(e.target.value),
                })
              }
              style={{ width: 60, marginLeft: 4 }}
            />
          </label>
          <label>
            中风险阈值（&ge;）：
            <input
              type="number"
              data-testid="risk-medium"
              value={config.risk_levels.medium}
              min={1}
              max={100}
              onChange={(e) =>
                updateGlobal("risk_levels", {
                  ...config.risk_levels,
                  medium: Number(e.target.value),
                })
              }
              style={{ width: 60, marginLeft: 4 }}
            />
          </label>
        </div>

        <label>
          元数据白名单（每行一个）：
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
            style={{ display: "block", width: "100%", marginTop: 4 }}
          />
        </label>

        <label>
          硬件关键词（每行一个）：
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
            style={{ display: "block", width: "100%", marginTop: 4 }}
          />
        </label>

        <div style={{ display: "flex", gap: 16 }}>
          <label>
            短段落过滤阈值：
            <input
              type="number"
              data-testid="min-paragraph-length"
              value={config.min_paragraph_length}
              min={1}
              onChange={(e) =>
                updateGlobal("min_paragraph_length", Number(e.target.value))
              }
              style={{ width: 60, marginLeft: 4 }}
            />
          </label>
          <label>
            文件保留天数：
            <input
              type="number"
              data-testid="file-retention-days"
              value={config.file_retention_days}
              min={1}
              onChange={(e) =>
                updateGlobal("file_retention_days", Number(e.target.value))
              }
              style={{ width: 60, marginLeft: 4 }}
            />
          </label>
        </div>
      </div>

      {/* 操作按钮 */}
      <div style={{ marginTop: 24, display: "flex", gap: 12 }}>
        <button
          data-testid="save-btn"
          onClick={handleSave}
          disabled={saving}
          style={{
            padding: "8px 24px",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          {saving ? "保存中..." : "保存"}
        </button>
        <button
          data-testid="restore-btn"
          onClick={handleRestore}
          disabled={saving}
          style={{ padding: "8px 24px", cursor: "pointer" }}
        >
          恢复默认
        </button>
      </div>
    </main>
  );
}

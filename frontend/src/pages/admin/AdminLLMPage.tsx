/**
 * LLM 配置页 (admin-llm-config, US-9.2)
 *
 * - Breadcrumb + 标题(同 AdminRulesPage / 详情页)
 * - Card:基本配置(provider Select / api_key Password / model / base_url / timeout)
 * - Card:测试连接(按钮 + 结果 Alert)
 * - 底部操作条:恢复默认 + 保存
 *
 * Req-6:api_key 输入框 placeholder = 当前脱敏值;空白输入 → 后端保持旧值
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  App,
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Typography,
} from "antd";
import {
  ExperimentOutlined,
  SaveOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { ApiError, api } from "../../services/api";
import type { LLMConfigResponse, LLMTestResponse } from "../../types";

const DEFAULT_CONFIG: LLMConfigResponse = {
  provider: "dashscope",
  api_key_masked: "",
  model: "qwen-plus",
  base_url: null,
  timeout_s: 30,
  source: "default",
};

const PROVIDER_OPTIONS = [
  { value: "dashscope", label: "阿里百炼 DashScope" },
  { value: "openai", label: "OpenAI" },
  { value: "custom", label: "自定义(OpenAI 兼容)" },
];

const SOURCE_LABELS: Record<string, string> = {
  db: "已从后台保存",
  env: "来自环境变量(未在后台保存过)",
  default: "使用系统默认值",
};

export default function AdminLLMPage() {
  const { message } = App.useApp();

  const [cfg, setCfg] = useState<LLMConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<LLMTestResponse | null>(null);
  const [error, setError] = useState("");

  // 表单状态(受控)
  const [provider, setProvider] = useState<string>("dashscope");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("qwen-plus");
  const [baseUrl, setBaseUrl] = useState<string>("");
  const [timeoutS, setTimeoutS] = useState(30);

  const syncFormFromCfg = (c: LLMConfigResponse) => {
    setProvider(c.provider);
    setModel(c.model);
    setBaseUrl(c.base_url ?? "");
    setTimeoutS(c.timeout_s);
    setApiKey(""); // 不回填,留给 placeholder 显示脱敏
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const c = await api.getLLMConfig();
      setCfg(c);
      syncFormFromCfg(c);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const updated = await api.updateLLMConfig({
        provider,
        api_key: apiKey || undefined, // 空值不传,后端保持旧值
        model: model.trim(),
        base_url: baseUrl.trim() || null,
        timeout_s: timeoutS,
      });
      setCfg(updated);
      syncFormFromCfg(updated);
      void message.success("保存成功");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testLLMConnection({
        provider,
        api_key: apiKey || undefined,
        model: model.trim(),
        base_url: baseUrl.trim() || null,
        timeout_s: Math.min(timeoutS, 10),
      });
      setTestResult(r);
    } catch (e) {
      setTestResult({
        ok: false,
        latency_ms: 0,
        error: e instanceof ApiError ? `HTTP ${e.status}` : "请求失败",
      });
    } finally {
      setTesting(false);
    }
  }

  function handleRestore() {
    setProvider(DEFAULT_CONFIG.provider);
    setApiKey("");
    setModel(DEFAULT_CONFIG.model);
    setBaseUrl(DEFAULT_CONFIG.base_url ?? "");
    setTimeoutS(DEFAULT_CONFIG.timeout_s);
    setTestResult(null);
    void message.info("已重置为系统默认值,点击保存才会生效");
  }

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: "center" }}>
        <Spin tip="加载中..." />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 880 }}>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">首页</Link> },
          { title: "管理" },
          { title: "LLM 配置" },
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
          <Typography.Title level={3} style={{ margin: 0, fontWeight: 600, fontSize: 22 }}>
            LLM 配置
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 13 }}>
            配置检测流水线所用的大模型 provider、API Key 和参数;保存即时生效,无需重启服务
          </Typography.Paragraph>
        </div>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 来源提示 */}
      {cfg && (
        <Alert
          type={cfg.source === "db" ? "success" : "info"}
          showIcon
          message={
            <span style={{ fontSize: 13 }}>
              当前配置:<b>{SOURCE_LABELS[cfg.source] ?? cfg.source}</b>
              {cfg.source !== "db" && (
                <span style={{ color: "#8a919d", marginLeft: 8 }}>
                  点击"保存"后将固化到后台,不再依赖 env
                </span>
              )}
            </span>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 基本配置 */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 24 } }}
        style={{ marginBottom: 16 }}
      >
        <Typography.Title level={5} style={{ margin: "0 0 16px", fontWeight: 600 }}>
          基本配置
        </Typography.Title>

        <Form layout="vertical" requiredMark={false} size="large">
          <Form.Item label="Provider" extra="选择 LLM 供应商;custom 需填 Base URL">
            <Select
              value={provider}
              onChange={setProvider}
              options={PROVIDER_OPTIONS}
              data-testid="llm-provider"
              style={{ maxWidth: 320 }}
            />
          </Form.Item>

          <Form.Item
            label="API Key"
            extra={
              apiKey
                ? "保存后将更新 key(末 4 位保留用于识别)"
                : cfg?.api_key_masked
                  ? `当前:${cfg.api_key_masked}(留空则保持不变)`
                  : "尚未配置,请填入 API Key"
            }
          >
            <Input.Password
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={cfg?.api_key_masked || "sk-..."}
              data-testid="llm-api-key"
              autoComplete="new-password"
            />
          </Form.Item>

          <Form.Item label="Model" extra="如 qwen-plus / gpt-4o-mini">
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              data-testid="llm-model"
              style={{ maxWidth: 320 }}
            />
          </Form.Item>

          <Form.Item
            label="Base URL"
            extra={
              provider === "custom"
                ? "必填:OpenAI 兼容端点 URL"
                : "选填:留空使用 provider 默认端点"
            }
          >
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={
                provider === "openai"
                  ? "https://api.openai.com/v1"
                  : provider === "dashscope"
                    ? "https://dashscope.aliyuncs.com/compatible-mode/v1"
                    : "https://your-endpoint.com/v1"
              }
              data-testid="llm-base-url"
            />
          </Form.Item>

          <Form.Item
            label="Timeout(秒)"
            extra="单次调用超时;1~300 秒"
            style={{ marginBottom: 0 }}
          >
            <InputNumber
              value={timeoutS}
              onChange={(v) => setTimeoutS(Number(v) || 30)}
              min={1}
              max={300}
              data-testid="llm-timeout"
              style={{ width: 120 }}
            />
          </Form.Item>
        </Form>
      </Card>

      {/* 测试连接 */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 20 } }}
        style={{ marginBottom: 16 }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <Typography.Title level={5} style={{ margin: 0, fontWeight: 600 }}>
              测试连接
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 12.5 }}>
              用当前表单值发一个最小请求验证 provider 和 key 可用(max_tokens=1,消耗极低)
            </Typography.Paragraph>
          </div>
          <Button
            icon={<ExperimentOutlined />}
            onClick={handleTest}
            loading={testing}
            data-testid="llm-test-btn"
          >
            测试连接
          </Button>
        </div>

        {testResult && (
          <Alert
            type={testResult.ok ? "success" : "error"}
            showIcon
            data-testid="llm-test-result"
            message={
              testResult.ok
                ? `连接成功 · 耗时 ${testResult.latency_ms} ms`
                : `连接失败 · ${testResult.error ?? "未知错误"}`
            }
            style={{ marginTop: 12 }}
          />
        )}
      </Card>

      {/* 底部操作条 */}
      <Card variant="outlined" styles={{ body: { padding: "14px 20px" } }}>
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            gap: 8,
          }}
        >
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12, marginRight: "auto" }}
          >
            保存后对所有检测维度立即生效
          </Typography.Text>
          <Button
            icon={<UndoOutlined />}
            onClick={handleRestore}
            disabled={saving}
            data-testid="llm-restore-btn"
          >
            恢复默认
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            data-testid="llm-save-btn"
          >
            保存
          </Button>
        </div>
      </Card>

      {/* 供 Space 用作占位,防 lint 告警 */}
      {false && <Space />}
    </div>
  );
}

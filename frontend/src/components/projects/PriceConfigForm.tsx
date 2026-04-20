/**
 * 项目报价元配置表单 (US-4.4, C4 file-upload §8.5)
 *
 * GET → 回显;PUT → 创建或更新。首次 GET 返 null 时显示默认值占位。
 *
 * antd 化:Select / Checkbox / Button;data-testid 保留在 wrapper 上,
 * 测试里用 wrapper.querySelector('.ant-select-selector') 打开下拉。
 */
import { useEffect, useState } from "react";
import { Button, Checkbox, Select, Space, Typography } from "antd";
import { CheckOutlined } from "@ant-design/icons";
import { api } from "../../services/api";
import type { Currency, PriceConfig, UnitScale } from "../../types";

interface Props {
  projectId: number;
}

const CURRENCIES: Currency[] = ["CNY", "USD", "EUR", "HKD"];
const UNIT_SCALES: UnitScale[] = ["yuan", "wan_yuan", "fen"];
const UNIT_LABEL: Record<UnitScale, string> = {
  yuan: "元",
  wan_yuan: "万元",
  fen: "分",
};

export default function PriceConfigForm({ projectId }: Props) {
  const [cfg, setCfg] = useState<PriceConfig | null>(null);
  const [currency, setCurrency] = useState<Currency>("CNY");
  const [taxInclusive, setTaxInclusive] = useState(true);
  const [unitScale, setUnitScale] = useState<UnitScale>("yuan");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const resp = await api.getPriceConfig(projectId);
        if (cancelled) return;
        if (resp) {
          setCfg(resp);
          setCurrency(resp.currency as Currency);
          setTaxInclusive(resp.tax_inclusive);
          setUnitScale(resp.unit_scale as UnitScale);
        }
      } catch {
        if (!cancelled) setError("加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.putPriceConfig(projectId, {
        currency,
        tax_inclusive: taxInclusive,
        unit_scale: unitScale,
      });
      setCfg(updated);
      setSavedAt(new Date().toLocaleTimeString());
    } catch {
      setError("保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <Typography.Text data-testid="price-config-loading" type="secondary">
        加载中...
      </Typography.Text>
    );
  }

  return (
    <div data-testid="price-config-form">
      <Space size={20} wrap align="center">
        <span>
          <Typography.Text type="secondary" style={{ fontSize: 13, marginRight: 8 }}>
            币种
          </Typography.Text>
          <span data-testid="price-config-currency">
            <Select
              value={currency}
              onChange={(v) => setCurrency(v as Currency)}
              style={{ width: 96 }}
              options={CURRENCIES.map((c) => ({ value: c, label: c }))}
            />
          </span>
        </span>

        <span data-testid="price-config-tax">
          <Checkbox
            checked={taxInclusive}
            onChange={(e) => setTaxInclusive(e.target.checked)}
          >
            含税
          </Checkbox>
        </span>

        <span>
          <Typography.Text type="secondary" style={{ fontSize: 13, marginRight: 8 }}>
            单位
          </Typography.Text>
          <span data-testid="price-config-unit">
            <Select
              value={unitScale}
              onChange={(v) => setUnitScale(v as UnitScale)}
              style={{ width: 110 }}
              options={UNIT_SCALES.map((u) => ({ value: u, label: UNIT_LABEL[u] }))}
            />
          </span>
        </span>

        <Button
          type="primary"
          icon={<CheckOutlined />}
          onClick={save}
          loading={saving}
          data-testid="price-config-save"
        >
          {saving ? "保存中" : cfg ? "更新" : "保存"}
        </Button>

        {savedAt && (
          <Typography.Text type="success" style={{ fontSize: 12 }}>
            已保存 {savedAt}
          </Typography.Text>
        )}
        {error && (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            {error}
          </Typography.Text>
        )}
      </Space>
    </div>
  );
}

/**
 * 项目报价元配置表单 (US-4.4, C4 file-upload §8.5)。
 *
 * GET → 回显;PUT → 创建或更新。首次 GET 返 null 时显示默认值占位。
 */
import { useEffect, useState } from "react";
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
      } catch (err) {
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
    } catch (err) {
      setError("保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p data-testid="price-config-loading">加载中...</p>;
  }

  return (
    <div data-testid="price-config-form" style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
      <label>
        币种
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value as Currency)}
          data-testid="price-config-currency"
          style={{ marginLeft: 4 }}
        >
          {CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <label>
        含税
        <input
          type="checkbox"
          checked={taxInclusive}
          onChange={(e) => setTaxInclusive(e.target.checked)}
          data-testid="price-config-tax"
          style={{ marginLeft: 4 }}
        />
      </label>
      <label>
        单位
        <select
          value={unitScale}
          onChange={(e) => setUnitScale(e.target.value as UnitScale)}
          data-testid="price-config-unit"
          style={{ marginLeft: 4 }}
        >
          {UNIT_SCALES.map((u) => (
            <option key={u} value={u}>
              {UNIT_LABEL[u]}
            </option>
          ))}
        </select>
      </label>
      <button
        onClick={save}
        disabled={saving}
        data-testid="price-config-save"
        style={{ padding: "4px 16px" }}
      >
        {saving ? "保存中..." : cfg ? "更新" : "保存"}
      </button>
      {savedAt && (
        <span style={{ color: "#52c41a", fontSize: 12 }}>已保存 {savedAt}</span>
      )}
      {error && <span style={{ color: "#c00", fontSize: 12 }}>{error}</span>}
    </div>
  );
}

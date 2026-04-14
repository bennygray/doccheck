/**
 * 创建项目页 (C3 project-mgmt, US-2.1)
 *
 * - 4 字段:name(必填)/ bid_code / max_price / description
 * - 本地 useState 校验(不引 form 库,遵循 C2 同款朴素风格)
 * - max_price 为空时显示 US-2.1 提示文案,提醒"报价接近限价"维度将跳过
 * - 提交成功跳详情页
 */
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../../services/api";

function validateMaxPrice(raw: string): string | null {
  if (raw.trim() === "") return null; // 选填
  const n = Number(raw);
  if (!Number.isFinite(n)) return "最高限价必须是数字";
  if (n < 0) return "最高限价不能为负数";
  // 两位小数限制(与后端 DECIMAL(18,2) 对齐)
  if (/\.\d{3,}$/.test(raw.trim())) return "最高限价最多保留两位小数";
  return null;
}

export default function ProjectCreatePage() {
  const [name, setName] = useState("");
  const [bidCode, setBidCode] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const showNoPriceHint = useMemo(() => maxPrice.trim() === "", [maxPrice]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (name.trim() === "") {
      setError("项目名称不能为空");
      return;
    }
    if (name.length > 100) {
      setError("项目名称不能超过 100 字符");
      return;
    }
    if (bidCode.length > 50) {
      setError("招标编号不能超过 50 字符");
      return;
    }
    if (description.length > 500) {
      setError("项目描述不能超过 500 字符");
      return;
    }
    const priceError = validateMaxPrice(maxPrice);
    if (priceError) {
      setError(priceError);
      return;
    }

    setSubmitting(true);
    try {
      const created = await api.createProject({
        name: name.trim(),
        bid_code: bidCode.trim() || null,
        max_price: maxPrice.trim() === "" ? null : maxPrice.trim(),
        description: description.trim() || null,
      });
      navigate(`/projects/${created.id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`创建失败 (${err.status})`);
      } else {
        setError("创建失败,请稍后重试");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif", maxWidth: 640 }}>
      <header style={{ marginBottom: 16 }}>
        <Link to="/projects" data-testid="back-to-list">
          ← 返回项目列表
        </Link>
        <h1 style={{ fontSize: 22, marginTop: 12 }}>新建检测项目</h1>
      </header>

      <form onSubmit={onSubmit} data-testid="create-form">
        <label style={{ display: "block", marginTop: 12 }}>
          <span>项目名称 *</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            required
            data-testid="create-name"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        <label style={{ display: "block", marginTop: 12 }}>
          <span>招标编号</span>
          <input
            type="text"
            value={bidCode}
            onChange={(e) => setBidCode(e.target.value)}
            maxLength={50}
            data-testid="create-bid-code"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        <label style={{ display: "block", marginTop: 12 }}>
          <span>最高限价(元,最多两位小数)</span>
          <input
            type="text"
            inputMode="decimal"
            value={maxPrice}
            onChange={(e) => setMaxPrice(e.target.value)}
            data-testid="create-max-price"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
          {showNoPriceHint ? (
            <p
              data-testid="no-max-price-hint"
              style={{ color: "#c60", fontSize: 13, marginTop: 4 }}
            >
              未设置最高限价,将跳过"报价接近限价"维度检测
            </p>
          ) : null}
        </label>

        <label style={{ display: "block", marginTop: 12 }}>
          <span>项目描述</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            rows={4}
            data-testid="create-description"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        {error ? (
          <p
            data-testid="create-error"
            style={{ color: "#c00", marginTop: 12 }}
            role="alert"
          >
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          data-testid="create-submit"
          style={{
            marginTop: 16,
            padding: "8px 16px",
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? "创建中..." : "创建项目"}
        </button>
      </form>
    </main>
  );
}

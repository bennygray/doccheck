/**
 * 证据摘要翻译器 — 把后端 evidence_summary 的原始 JSON 翻成人话
 *
 * 后端 `_evidence_summary()` 拿不到 `summary`/`reason`/`conclusion` 字段时,
 * 会直接把 JSON 截断 200 字符抛回来,UI 看起来就是一坨原始数据。
 * 这里按维度解析常见字段,生成一句中文摘要。
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function summarizeMetaAuthor(p: any): string {
  const hits = Array.isArray(p.hits) ? p.hits : [];
  if (hits.length === 0) return "";
  const vals = hits
    .map((h: any) => (typeof h?.normalized === "string" ? h.normalized : h?.value))
    .filter((v: any) => typeof v === "string" && v);
  if (vals.length === 0) return `${hits.length} 处元数据相同`;
  const show = Array.from(new Set(vals)).slice(0, 3).join(" · ");
  const prefix = vals.length > 1 ? `${vals.length} 处作者相同:` : "作者相同:";
  return `${prefix}${show}`;
}

function summarizeMetaTime(p: any): string {
  const hits = Array.isArray(p.hits) ? p.hits : [];
  if (hits.length === 0) return "";
  const times = hits[0]?.times;
  if (!Array.isArray(times) || times.length === 0) return "时间元数据相同";
  const uniq = Array.from(new Set(times.filter((t: any) => typeof t === "string")));
  if (uniq.length === 1) {
    return `${times.length} 个文档提交时间完全相同:${formatTime(uniq[0] as string)}`;
  }
  return `${times.length} 个文档时间接近(${uniq.length} 个不同值)`;
}

function summarizeMetaMachine(p: any): string {
  const hits = Array.isArray(p.hits) ? p.hits : [];
  const hit = hits[0];
  if (!hit || !hit.value || typeof hit.value !== "object") return "机器指纹相同";
  const v = hit.value;
  const parts: string[] = [];
  if (typeof v.app_name === "string") {
    const app = v.app_name
      .replace(/microsoft\s+macintosh\s+word/i, "Microsoft Word (Mac)")
      .replace(/microsoft\s+word/i, "Microsoft Word");
    parts.push(app);
  }
  if (typeof v.template === "string") parts.push(v.template);
  if (typeof v.app_version === "string") {
    const major = v.app_version.split(".")[0];
    parts.push(`v${major}`);
  }
  const tail = parts.length ? `:${parts.join(" · ")}` : "";
  return `机器指纹一致${tail}`;
}

function summarizePrice(p: any): string {
  const sub = p.subdims;
  if (!sub || typeof sub !== "object") {
    if (p.score === 1 || p.score === 1.0) return "报价完全一致";
    return "";
  }
  const parts: string[] = [];
  const tailHits = sub.tail?.hits;
  if (Array.isArray(tailHits) && tailHits.length > 0) {
    const t = tailHits[0];
    const amount = Array.isArray(t?.rows_a) && t.rows_a[0]?.[2];
    const qty = tailHits.length > 1 ? `${tailHits.length} 处` : "";
    const amt = amount ? ` · ¥${amount}` : "";
    parts.push(`${qty}尾号 ${t.tail} 相同${amt}`);
  }
  const totalHits = sub.total?.hits;
  if (Array.isArray(totalHits) && totalHits.length > 0) {
    parts.push(`${totalHits.length} 处总价一致`);
  }
  const anomalyHits = sub.anomaly?.hits;
  if (Array.isArray(anomalyHits) && anomalyHits.length > 0) {
    parts.push(`${anomalyHits.length} 处异常报价`);
  }
  return parts.length ? parts.join(" · ") : "报价一致性命中";
}

function summarizeStructure(p: any): string {
  if (typeof p.doc_role === "string" && p.doc_role) {
    return `文档结构一致(${p.doc_role})`;
  }
  return "文档结构高度一致";
}

function summarizeText(p: any): string {
  const samples = Array.isArray(p.samples) ? p.samples : [];
  if (samples.length === 0) return "";
  const s0 = samples[0];
  const txt =
    typeof s0?.a_text === "string" && s0.a_text
      ? s0.a_text.replace(/\s+/g, "").slice(0, 28)
      : "";
  const more = samples.length > 1 ? ` · 共 ${samples.length} 段相同` : "";
  if (txt) return `相同段落:"${txt}…"${more}`;
  return `${samples.length} 段文本相同`;
}

export function summarizeEvidence(
  dimension: string,
  raw: string | null | undefined,
): string {
  if (!raw) return "";
  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch {
    /* 后端已经给出人话就直接显示 */
    return raw;
  }
  if (typeof parsed !== "object" || parsed === null) return String(parsed);

  /* 后端优先字段(summary/reason/conclusion)若有就直接用 */
  for (const key of ["summary", "reason", "conclusion"] as const) {
    const v = parsed[key];
    if (typeof v === "string" && v) return v;
  }

  switch (dimension) {
    case "metadata_author":
      return summarizeMetaAuthor(parsed);
    case "metadata_time":
      return summarizeMetaTime(parsed);
    case "metadata_machine":
      return summarizeMetaMachine(parsed);
    case "price_consistency":
    case "price_anomaly":
      return summarizePrice(parsed);
    case "structure_similarity":
      return summarizeStructure(parsed);
    case "text_similarity":
    case "section_similarity":
      return summarizeText(parsed);
    default:
      return "";
  }
}

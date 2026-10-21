export const BRAND = "Milestone";

export function usd(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e12) return `${sign}$${(a / 1e12).toFixed(digits)}T`;
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(digits)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(a >= 1e8 ? 0 : digits)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(0)}K`;
  return `${sign}$${a.toFixed(2)}`;
}

export function price(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function pct(v: number | null | undefined, digits = 1, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function shortDate(d: string | null | undefined): string {
  if (!d) return "—";
  const dt = new Date(d + (d.length === 10 ? "T00:00:00" : ""));
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

// SEC's industry titles are terse ("Services-Prepackaged Software"). A few
// codes also need context: 6199 is mostly crypto miners turning into AI hosts.
const INDUSTRY_NOTES: Record<string, string> = {
  "6199": "Finance services (mostly crypto miners → AI data centers)",
  "3443": "Fabricated plate work (incl. small nuclear reactors)",
  "7374": "Computer processing & data prep (incl. AI cloud hosts)",
};

export function industryName(title: string | null | undefined, sic?: string | null): string {
  if (sic && INDUSTRY_NOTES[sic]) return INDUSTRY_NOTES[sic];
  if (!title) return sic ? `SIC ${sic}` : "";
  let t = title.replace(/^Services-/i, "").replace(/,\s*Nec\b/i, "").replace(/\s*\(No .*?\)/i, "");
  t = t.toLowerCase().replace(/(^|[\s/&(-])([a-z])/g, (_m, p, c) => p + c.toUpperCase());
  return t.replace(/\b(And|Of|For|Or|In|To)\b/g, (m) => m.toLowerCase());
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "";
  return s.toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase()).replace(/\bInc\b/g, "Inc")
    .replace(/\b(Ai|Ii|Iii|Llc|Plc|Nv|Sa|Ag)\b/g, (m) => m.toUpperCase());
}

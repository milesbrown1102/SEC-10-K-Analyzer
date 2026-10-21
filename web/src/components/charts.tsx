import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import clsx from "clsx";
import { api } from "../lib/api";
import { shortDate } from "../lib/format";
import { Skeleton } from "./ui";

export const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
const AXIS = { stroke: "var(--axis)", tick: { fill: "var(--ink-3)", fontSize: 12 }, tickLine: false };

function TipBox({ title, rows }: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded-xl border border-line bg-raised px-3 py-2.5 text-xs shadow-card">
      <div className="mb-1.5 font-medium text-ink">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 py-0.5">
          {r.color && <span className="h-2.5 w-2.5 rounded-sm" style={{ background: r.color }} />}
          <span className="text-ink-3">{r.label}</span>
          <span className="ml-auto pl-4 font-medium tabular text-ink">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-2">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          {i.dashed
            ? <span className="w-4 border-t-2 border-dashed" style={{ borderColor: i.color }} />
            : <span className="h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />}
          {i.label}
        </span>
      ))}
    </div>
  );
}

/** Stock vs S&P 500, both indexed to 100 at the start of the range (one shared axis). */
export function PriceChart({ ticker, tall }: { ticker: string; tall?: boolean }) {
  const [years, setYears] = useState(1);
  const q = useQuery({ queryKey: ["prices", ticker, years], queryFn: () => api(`/prices/${ticker}?years=${years}`) });
  const data = useMemo(() => {
    if (!q.data?.prices?.length) return [];
    const spy = new Map<string, number>(q.data.spy.map((p: any) => [p.date, p.close]));
    const s0 = q.data.prices[0].close;
    const spy0 = spy.get(q.data.prices[0].date) ?? q.data.spy[0]?.close;
    return q.data.prices.map((p: any) => ({
      date: p.date,
      stock: (p.close / s0) * 100,
      spy: spy.has(p.date) && spy0 ? (spy.get(p.date)! / spy0) * 100 : null,
      close: p.close,
    }));
  }, [q.data]);
  const last = data[data.length - 1];
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <Legend items={[
          { label: `${ticker}${last ? ` ${last.stock >= 100 ? "+" : ""}${(last.stock - 100).toFixed(1)}%` : ""}`, color: "var(--s1)" },
          { label: `S&P 500${last?.spy ? ` ${last.spy >= 100 ? "+" : ""}${(last.spy - 100).toFixed(1)}%` : ""}`, color: "var(--ink-3)", dashed: true },
        ]} />
        <div className="flex gap-1 rounded-lg border border-line p-0.5">
          {[1, 3, 5].map((y) => (
            <button key={y} onClick={() => setYears(y)}
              className={clsx("rounded-md px-2.5 py-1 text-xs font-medium", years === y ? "bg-raised text-ink" : "text-ink-3 hover:text-ink")}>
              {y}Y
            </button>
          ))}
        </div>
      </div>
      {q.isLoading ? <Skeleton className={tall ? "h-[420px]" : "h-64"} /> : (
        <div className={tall ? "h-[420px]" : "h-64"}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" {...AXIS} minTickGap={48} tickFormatter={(d) => shortDate(d).replace(/, \d{4}$/, years > 1 ? "" : "")} />
              <YAxis {...AXIS} axisLine={false} domain={["auto", "auto"]} tickFormatter={(v) => `${(v - 100).toFixed(0)}%`} width={56} />
              <Tooltip cursor={{ stroke: "var(--ink-3)", strokeWidth: 1 }} content={({ active, payload }) =>
                active && payload?.length ? (
                  <TipBox title={shortDate(payload[0].payload.date)} rows={[
                    { label: ticker, value: `$${payload[0].payload.close.toFixed(2)} (${(payload[0].payload.stock - 100).toFixed(1)}%)`, color: "var(--s1)" },
                    ...(payload[0].payload.spy ? [{ label: "S&P 500", value: `${(payload[0].payload.spy - 100).toFixed(1)}%`, color: "var(--ink-3)" }] : []),
                  ]} />
                ) : null} />
              <Line dataKey="spy" stroke="var(--ink-3)" strokeWidth={2} strokeDasharray="4 4" dot={false} connectNulls isAnimationActive={false} />
              <Line dataKey="stock" stroke="var(--s1)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export const SOURCE_KEYS = ["giants", "scarcity", "funds", "insiders"] as const;
export const SOURCE_LABELS: Record<string, string> = {
  giants: "Giants investing", scarcity: "Scarcity rising", funds: "Top funds buying", insiders: "Insiders buying",
};

/** Horizontal stacked bars: each industry's points from the four evidence sources. */
export function SourceBars({ rows, onSelect, selected }: {
  rows: { sic: string; industry: string; breakdown: Record<string, number>; score: number }[];
  onSelect?: (sic: string) => void; selected?: string | null;
}) {
  const data = rows.map((r) => ({ ...r.breakdown, name: r.industry, sic: r.sic, score: r.score }));
  return (
    <div>
      <div className="mb-3"><Legend items={SOURCE_KEYS.map((k, i) => ({ label: SOURCE_LABELS[k], color: SERIES[i] }))} /></div>
      <div style={{ height: Math.max(220, data.length * 40) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }} barCategoryGap={10}
            onClick={(e: any) => e?.activePayload && onSelect?.(e.activePayload[0].payload.sic)}>
            <CartesianGrid stroke="var(--grid)" horizontal={false} />
            <XAxis type="number" {...AXIS} domain={[0, 100]} />
            <YAxis type="category" dataKey="name" {...AXIS} axisLine={false} width={270}
              tick={(props: any) => {
                const row = data[props.index];
                const sel = row?.sic === selected;
                return (
                  <text x={props.x - 8} y={props.y} dy={4} textAnchor="end" fontSize={12.5}
                    fill={sel ? "var(--ink)" : "var(--ink-2)"} fontWeight={sel ? 600 : 400} style={{ cursor: "pointer" }}>
                    {String(props.payload.value).length > 38 ? String(props.payload.value).slice(0, 37) + "…" : props.payload.value}
                  </text>
                );
              }} />
            <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} content={({ active, payload }) =>
              active && payload?.length ? (
                <TipBox title={`${payload[0].payload.name} · ${payload[0].payload.score.toFixed(0)}/100`}
                  rows={SOURCE_KEYS.map((k, i) => ({ label: SOURCE_LABELS[k], value: `${(payload[0].payload[k] ?? 0).toFixed(1)} / 25`, color: SERIES[i] }))} />
              ) : null} />
            {SOURCE_KEYS.map((k, i) => (
              <Bar key={k} dataKey={k} stackId="s" fill={SERIES[i]} stroke="var(--surface)" strokeWidth={2}
                radius={i === SOURCE_KEYS.length - 1 ? [0, 4, 4, 0] : 0} isAnimationActive={false} style={{ cursor: "pointer" }} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** Compact 4-segment bar for cards (same colors and order as SourceBars). */
export function MiniStack({ breakdown }: { breakdown: Record<string, number> }) {
  return (
    <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-raised" aria-hidden>
      {SOURCE_KEYS.map((k, i) => (breakdown[k] ?? 0) > 0 && (
        <div key={k} style={{ width: `${breakdown[k]}%`, background: SERIES[i] }} className="h-full first:rounded-l-full last:rounded-r-full" />
      ))}
    </div>
  );
}

export function ScoreRing({ score, size = 112 }: { score: number; size?: number }) {
  const r = (size - 12) / 2, c = 2 * Math.PI * r;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--raised)" strokeWidth={8} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--accent)" strokeWidth={8} fill="none"
          strokeDasharray={`${(c * Math.max(0, Math.min(100, score))) / 100} ${c}`} strokeLinecap="round" />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div><div className="text-3xl font-semibold tracking-tight">{score}</div><div className="text-[11px] text-ink-3">of 100</div></div>
      </div>
    </div>
  );
}

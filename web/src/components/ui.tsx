import { ReactNode, useEffect, useState } from "react";
import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, Info, Loader2, Minus } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "../lib/api";
import { ago } from "../lib/format";

export function Card({ children, className, pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <div className={clsx("card", pad && "card-pad", className)}>{children}</div>;
}

export function SectionTitle({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="h-section">{title}</h2>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink-3">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function PageHeader({ eyebrow, title, subtitle, right }: {
  eyebrow?: string; title: ReactNode; subtitle?: ReactNode; right?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
        <h1 className="h-page">{title}</h1>
        {subtitle && <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

/** Up/down change with an arrow icon + sign, so meaning never rides on color alone. */
export function Delta({ value, suffix = "%", digits = 1, label, size = "sm" }: {
  value: number | null | undefined; suffix?: string; digits?: number; label?: string; size?: "sm" | "md";
}) {
  if (value === null || value === undefined) return <span className="text-ink-3">—</span>;
  const up = value > 0.05, down = value < -0.05;
  const Icon = up ? ArrowUpRight : down ? ArrowDownRight : Minus;
  return (
    <span className={clsx("pill tabular", size === "md" && "px-2.5 py-1 text-sm",
      up ? "bg-good/15 text-[#5fd35f]" : down ? "bg-bad/15 text-[#ff8a8a]" : "bg-raised text-ink-3")}>
      <Icon size={size === "md" ? 15 : 13} aria-hidden />
      {value > 0 ? "+" : ""}{value.toFixed(digits)}{suffix}{label ? ` ${label}` : ""}
    </span>
  );
}

export function Stat({ label, value, sub, hint }: { label: string; value: ReactNode; sub?: ReactNode; hint?: string }) {
  return (
    <div className="card card-pad">
      <div className="eyebrow flex items-center gap-1">{label}{hint && <span title={hint}><Info size={12} /></span>}</div>
      <div className="mt-2 text-[28px] font-semibold leading-tight tracking-tight text-ink">{value}</div>
      {sub && <div className="mt-1.5 text-sm text-ink-3">{sub}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} aria-hidden />;
}

export function LoadingCards({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card card-pad flex flex-col items-start gap-3">
      <div className="text-sm font-semibold text-ink">{title}</div>
      {children && <div className="max-w-2xl text-sm text-ink-3">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-[#ff8a8a]">
      {error instanceof Error ? error.message : "Something went wrong."}
    </div>
  );
}

export function Callout({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "caution" }) {
  return (
    <div className={clsx("flex gap-3 rounded-xl border px-4 py-3 text-sm leading-relaxed",
      tone === "info" ? "border-accent/25 bg-accent-soft text-ink-2" : "border-warn/30 bg-warn/10 text-ink-2")}>
      <Info size={16} className={clsx("mt-0.5 shrink-0", tone === "info" ? "text-accent" : "text-warn")} />
      <div>{children}</div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="mb-5 flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={clsx("rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors",
            value === t.id ? "bg-raised text-ink shadow-card" : "text-ink-3 hover:text-ink")}>
          {t.label}{t.count !== undefined && <span className="ml-1.5 text-ink-3">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "accent" | "good" | "bad" | "warn" }) {
  const tones = {
    neutral: "bg-raised text-ink-2 border-line",
    accent: "bg-accent-soft text-[#8fbcf2] border-accent/30",
    good: "bg-good/15 text-[#5fd35f] border-good/30",
    bad: "bg-bad/15 text-[#ff8a8a] border-bad/30",
    warn: "bg-warn/10 text-warn border-warn/30",
  };
  return <span className={clsx("pill border", tones[tone])}>{children}</span>;
}

/**
 * Starts a backend background job and polls its status until done, then
 * refreshes the given queries. Status endpoints share {in_progress, done,
 * total, stage, error, generated_at}.
 */
export function JobButton({ start, status, invalidate, label, hint }: {
  start: string; status: string; invalidate: string[][]; label: string; hint?: string;
}) {
  const qc = useQueryClient();
  const [polling, setPolling] = useState(false);
  const st = useQuery({
    queryKey: ["status", status],
    queryFn: () => api(status),
    refetchInterval: polling ? 2500 : false,
  });
  const running = polling || st.data?.in_progress;
  useEffect(() => {
    if (polling && st.data && !st.data.in_progress) {
      setPolling(false);
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    }
  }, [polling, st.data, invalidate, qc]);
  useEffect(() => { if (st.data?.in_progress) setPolling(true); }, [st.data?.in_progress]);

  const progress = st.data?.total ? `${st.data.stage ? st.data.stage + " · " : ""}${st.data.done}/${st.data.total}` : "working…";
  return (
    <div className="flex items-center gap-3">
      {!running && st.data?.generated_at && <span className="text-xs text-ink-3">Updated {ago(st.data.generated_at)}</span>}
      <button className="btn-ghost" disabled={running} title={hint}
        onClick={async () => { try { await post(start, {}); } catch { /* already running */ } setPolling(true); }}>
        {running && <Loader2 size={15} className="animate-spin" />}
        {running ? progress : label}
      </button>
    </div>
  );
}

export function Disclaimer() {
  return (
    <p className="mx-auto max-w-4xl px-6 py-10 text-center text-xs leading-relaxed text-ink-3">
      Research tool, not investment advice. Signals come from public SEC filings and market data and can be
      wrong, late or incomplete. Backtested results don't guarantee future returns. Do your own research.
    </p>
  );
}

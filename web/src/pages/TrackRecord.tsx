import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiOrNull } from "../lib/api";
import { pct, shortDate } from "../lib/format";
import { Callout, Card, Delta, Empty, JobButton, LoadingCards, PageHeader } from "../components/ui";
import { Legend } from "../components/charts";

const LABELS: Record<string, string> = {
  score: "Total buy score", own_tightness: "Supplier's own scarcity", growth_adjusted_sales_yield: "Valuation vs growth",
  signal_confidence: "Mega-cap bottleneck signal", quarterly_revenue_growth_pct: "Revenue growth", relative_volume: "Relative volume",
  earnings_yield: "Earnings yield", sales_yield: "Sales yield", fcf_yield: "Free-cash-flow yield", insider_buyers: "Insider buyers",
  matched: "Matched to a bottleneck", thesis_intact: "Mega-cap CapEx > 25%", rel_volume_gt_2: "Volume spike", above_200sma: "Above 200-day avg",
  revenue_growth_gt_25: "Revenue growth > 25%", confirmed_deal: "Commercial 8-K deal", market_control_leader: "Revenue leader",
  own_tightness_any: "Any own scarcity", insider_buy_any: "Any insider buying", insider_cluster: "Insider cluster",
};

function verdict(ic: number | null, t: number | null) {
  if (ic === null || t === null) return <span className="text-ink-3">—</span>;
  if (ic > 0 && t >= 2) return <span className="text-[#5fd35f]">✓ predictive</span>;
  if (ic < 0 && t <= -2) return <span className="text-[#ff8a8a]">✗ wrong way</span>;
  return <span className="text-ink-3">noise</span>;
}

export default function TrackRecord() {
  const bt = useQuery({ queryKey: ["backtest"], queryFn: () => apiOrNull("/backtest/latest") });
  const rb = useQuery({ queryKey: ["radar-backtest"], queryFn: () => apiOrNull("/radar-backtest/latest") });
  const live = useQuery({ queryKey: ["track"], queryFn: () => apiOrNull("/scanner/track-record") });
  const a = bt.data?.analysis;
  const strat = a?.strategy_all;
  const ic3 = a?.ic?.["3"] ?? [];
  const score = ic3.find((r: any) => r.factor === "score");
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Track record" title="Does any of this actually work?"
        subtitle="Every signal is tested on history using only what was public at the time. Here's what held up, what didn't, and how live picks are doing. Nothing on this page is hidden or cherry-picked."
        right={<div className="flex flex-wrap gap-2"><JobButton start="/backtest/run" status="/backtest/status" invalidate={[["backtest"]]} label="Re-run score backtest" />
          <JobButton start="/radar-backtest/run" status="/radar-backtest/status" invalidate={[["radar-backtest"]]} label="Re-run radar backtest" /></div>} />

      {bt.isLoading ? <LoadingCards /> : !a ? <Empty title="No backtest yet">Run the score backtest (10–20 minutes the first time).</Empty> : <>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Card><div className="eyebrow">Buy score, rank correlation</div><div className="mt-2 text-3xl font-semibold tabular">{score?.mean_ic >= 0 ? "+" : ""}{score?.mean_ic?.toFixed(3)}</div>
            <div className="mt-1 text-sm text-ink-3">t-stat {score?.t_stat} over {score?.n_dates} quarters: {score?.t_stat >= 2 ? "predictive" : "right direction, not proven"}</div></Card>
          <Card><div className="eyebrow">Top-5 picks, per year</div><div className="mt-2 text-3xl font-semibold tabular">{pct(strat?.cagr_strategy)}</div>
            <div className="mt-1 text-sm text-ink-3">vs {pct(strat?.cagr_universe)} for the whole universe, {pct(strat?.cagr_spy)} S&P 500</div></Card>
          <Card><div className="eyebrow">Quarters beating the universe</div><div className="mt-2 text-3xl font-semibold tabular">{strat?.quarters_beating_universe} / {strat?.quarters}</div>
            <div className="mt-1 text-sm text-ink-3">{bt.data.start} → {bt.data.end}</div></Card>
        </div>
        <Callout tone="caution">The 17-stock universe was chosen in 2026 with hindsight, so "universe beat the S&P 500" means little. What matters is whether the score ranks stocks <i>within</i> it well.</Callout>
        <Card>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h2 className="h-section">Growth of $1, rebalanced quarterly</h2>
            <Legend items={[{ label: "Top 5 by score", color: "var(--s1)" }, { label: "Equal-weight universe", color: "var(--s2)" }, { label: "S&P 500", color: "var(--ink-3)", dashed: true }]} /></div>
          <div className="h-72"><ResponsiveContainer width="100%" height="100%">
            <LineChart data={strat?.curve ?? []} margin={{ left: -8, right: 8 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" stroke="var(--axis)" tick={{ fill: "var(--ink-3)", fontSize: 12 }} tickLine={false}
                ticks={(strat?.curve ?? []).filter((c: any) => c.date.slice(5, 7) === "03").map((c: any) => c.date)} tickFormatter={(d) => d.slice(0, 4)} />
              <YAxis scale="log" domain={["auto", "auto"]} stroke="var(--axis)" axisLine={false} tickLine={false} tick={{ fill: "var(--ink-3)", fontSize: 12 }} tickFormatter={(v) => `$${v.toFixed(v < 10 ? 1 : 0)}`} />
              <Tooltip contentStyle={{ background: "var(--raised)", border: "1px solid var(--line)", borderRadius: 12 }} labelFormatter={(d) => shortDate(d as string)}
                formatter={(v: number, n: string) => [`$${v.toFixed(2)}`, n === "strategy" ? "Top 5" : n === "universe" ? "Universe" : "S&P 500"]} />
              <Line dataKey="spy" stroke="var(--ink-3)" strokeDasharray="4 4" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="universe" stroke="var(--s2)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="strategy" stroke="var(--s1)" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart></ResponsiveContainer></div>
        </Card>
        <Card pad={false}>
          <div className="px-6 pt-6"><h2 className="h-section">Which factors predicted returns (3 months)</h2>
            <p className="mt-1 text-sm text-ink-3">Rank correlation with next-quarter return relative to the universe, averaged over quarters. Around 0.05–0.10 is useful; |t| under 2 is noise.</p></div>
          <div className="mt-4 overflow-x-auto"><table className="table-base">
            <thead><tr><th>Factor</th><th className="text-right">IC</th><th className="text-right">t-stat</th><th className="text-right">Quarters positive</th><th>Verdict</th></tr></thead>
            <tbody>{ic3.map((r: any) => (
              <tr key={r.factor}><td className={r.factor === "score" ? "font-semibold text-ink" : ""}>{LABELS[r.factor] ?? r.factor}</td>
                <td className="text-right tabular">{r.mean_ic?.toFixed(3) ?? "—"}</td><td className="text-right tabular">{r.t_stat ?? "—"}</td>
                <td className="text-right tabular">{r.pct_positive != null ? `${r.pct_positive}%` : "—"}</td><td>{verdict(r.mean_ic, r.t_stat)}</td></tr>))}</tbody></table></div>
        </Card>
      </>}

      {rb.data && (
        <Card pad={false}>
          <div className="px-6 pt-6"><h2 className="h-section">Scarcity radar: does new scarcity language precede gains?</h2>
            <p className="mt-1 text-sm text-ink-3">{rb.data.events.toLocaleString()} company-quarters since 2016 vs small caps (IWM), 12 months later. Price data for {rb.data.coverage_pct}%: delisted companies are missing, which flatters results.</p></div>
          <div className="mt-4 overflow-x-auto"><table className="table-base">
            <thead><tr><th>Group</th><th className="text-right">Companies</th><th className="text-right">Average</th><th className="text-right">Median</th><th className="text-right">Share beating</th><th className="text-right">t-stat</th></tr></thead>
            <tbody>{[["new", "Newly saying it"], ["persistent", "Already saying it"], ["new_with_insider_buying", "Newly saying it + insiders buying"], ["all", "Everyone saying it"]].map(([k, l]) => {
              const r = rb.data.results[k]["IWM_12m"];
              return <tr key={k}><td className="text-ink">{l}</td><td className="text-right tabular">{r.events}</td><td className="text-right"><Delta value={r.mean_excess_pct} /></td>
                <td className="text-right"><Delta value={r.median_excess_pct} /></td><td className="text-right tabular">{r.pct_beating}%</td><td className="text-right tabular">{r.t_stat}</td></tr>;
            })}</tbody></table></div>
          <p className="px-6 py-4 text-sm text-ink-3">Positive averages with negative medians mean a few big winners carry the group. That's lottery-like, not a reliable edge.</p>
        </Card>
      )}

      <Card pad={false}>
        <div className="px-6 pt-6"><h2 className="h-section">Live track record</h2>
          <p className="mt-1 text-sm text-ink-3">Every scan's picks at the price on the day, followed forward. No hindsight; it grows with each weekly scan.</p></div>
        {live.data?.picks?.length ? (
          <div className="mt-4 overflow-x-auto"><table className="table-base">
            <thead><tr><th>Scan date</th><th>Ticker</th><th className="text-right">Score</th><th className="text-right">Since</th><th className="text-right">S&P 500</th></tr></thead>
            <tbody>{live.data.picks.slice(0, 60).map((p: any, i: number) => (
              <tr key={i}><td>{shortDate(p.scan_date)}</td><td className="font-medium text-ink">{p.ticker}</td><td className="text-right tabular">{p.score}</td>
                <td className="text-right"><Delta value={p.return_pct} /></td><td className="text-right tabular">{pct(p.spy_return_pct)}</td></tr>))}</tbody></table></div>
        ) : <p className="px-6 pb-6 pt-3 text-sm text-ink-3">No recorded picks yet.</p>}
      </Card>
    </div>
  );
}

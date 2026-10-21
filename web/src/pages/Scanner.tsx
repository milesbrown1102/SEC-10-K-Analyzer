import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiOrNull } from "../lib/api";
import { pct } from "../lib/format";
import { Badge, Callout, Card, Empty, JobButton, LoadingCards, PageHeader } from "../components/ui";

export default function Scanner() {
  const q = useQuery({ queryKey: ["scan"], queryFn: () => apiOrNull("/scanner/latest") });
  const ev = q.data?.score_evidence?.score;
  const scores = [...(q.data?.buy_scores ?? [])].sort((a: any, b: any) => b.score - a.score);
  const signals = q.data?.signals ?? [];
  return (
    <div>
      <PageHeader eyebrow="Bottleneck scanner" title="Supplier buy scores"
        subtitle="Reads the mega-caps' 10-Ks for bottlenecks, then scores the companies that supply them (plus any you've added) on their own filings, valuation, growth, trend and deals."
        right={<JobButton start="/scanner/run" status="/scanner/status" invalidate={[["scan"]]} label="Run scan" />} />
      {ev && <div className="mb-6"><Callout tone={ev.t_stat >= 2 ? "info" : "caution"}>
        In the 2017–2026 backtest, this score's rank correlation with next-quarter relative returns was {ev.mean_ic >= 0 ? "+" : ""}{ev.mean_ic.toFixed(3)} (t {ev.t_stat}): {ev.t_stat >= 2 ? "predictive." : "pointing the right way, but not statistically proven."} <Link to="/track-record" className="link">Details</Link>
      </Callout></div>}
      {q.isLoading ? <LoadingCards /> : !q.data ? <Empty title="No scan yet">Click “Run scan”.</Empty> : (
        <div className="space-y-6">
          <Card pad={false}>
            <div className="overflow-x-auto"><table className="table-base">
              <thead><tr><th>Ticker</th><th>Score</th><th>Industry</th><th>Flagged by</th><th className="text-right">Own scarcity</th><th className="text-right">Insiders 90d</th><th className="text-right">Rev growth FY</th><th>Cautions</th></tr></thead>
              <tbody>{scores.map((s: any) => (
                <tr key={s.ticker}>
                  <td><Link to={`/company/${s.ticker}`} className="font-semibold text-ink hover:text-accent">{s.ticker}</Link></td>
                  <td className="w-44"><div className="flex items-center gap-2.5"><div className="h-1.5 w-20 rounded-full bg-raised"><div className="h-full rounded-full bg-accent" style={{ width: `${s.score}%` }} /></div><span className="tabular text-ink">{s.score}</span></div></td>
                  <td className="max-w-[240px] text-xs">{s.industry_label}</td>
                  <td className="text-xs">{s.matched ? s.mega_cap_ticker : "—"}</td>
                  <td className="text-right tabular">{s.own_tightness?.mentions ?? "—"}</td>
                  <td className="text-right tabular">{s.insider?.buyers ?? "—"}</td>
                  <td className="text-right tabular">{pct(s.valuation?.revenue_growth_annual, 0)}</td>
                  <td>{s.caution_flags?.length ? <Badge tone="warn">{s.caution_flags.length}</Badge> : <Badge tone="good">none</Badge>}</td>
                </tr>))}</tbody></table></div>
          </Card>
          <Card>
            <h2 className="h-section">What the mega-caps' filings flagged</h2>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
              {signals.map((s: any) => (
                <div key={s.id} className="rounded-xl border border-line p-4">
                  <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">{s.mega_cap_ticker}</Badge><span className="text-sm font-medium text-ink">{s.category}</span><span className="ml-auto text-xs tabular text-ink-3">{Math.round(s.confidence * 100)}%</span></div>
                  <p className="mt-2 line-clamp-4 text-sm leading-relaxed text-ink-2">“{s.evidence.split("\n\n")[0]}”</p>
                </div>))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiOrNull } from "../lib/api";
import { industryName, titleCase } from "../lib/format";
import { Badge, Callout, Card, Empty, JobButton, LoadingCards, PageHeader } from "../components/ui";
import { SERIES, SOURCE_KEYS, SOURCE_LABELS, SourceBars } from "../components/charts";

const SOURCE_HELP: Record<string, string> = {
  giants: "Mega-caps investing (other companies' 8-Ks + the giants' own 13Fs, last 12 months).",
  scarcity: "More companies in the industry newly saying their own product is scarce (SEC full-text search).",
  funds: "Net buyers among 18 tracked managers last quarter (13F).",
  insiders: "Clusters of executives buying their own stock, last 90 days (Form 4).",
};

export default function Industries() {
  const [params, setParams] = useSearchParams();
  const [weights, setWeights] = useState<Record<string, number>>({ giants: 1, scarcity: 1, funds: 1, insiders: 1 });
  const q = useQuery({ queryKey: ["opportunities"], queryFn: () => apiOrNull("/opportunities/latest") });

  const ranked = useMemo(() => {
    const rows = (q.data?.industries ?? []).map((r: any) => {
      const breakdown = Object.fromEntries(SOURCE_KEYS.map((k) => [k, (r.breakdown[k] ?? 0) * weights[k]]));
      const maxPossible = SOURCE_KEYS.reduce((s, k) => s + 25 * weights[k], 0) || 1;
      const raw = SOURCE_KEYS.reduce((s, k) => s + breakdown[k], 0);
      return { ...r, breakdown, score: (raw / maxPossible) * 100,
        sources_present: SOURCE_KEYS.filter((k) => breakdown[k] > 0).length };
    });
    return rows.sort((a: any, b: any) => b.sources_present - a.sources_present || b.score - a.score);
  }, [q.data, weights]);

  const selectedSic = params.get("sic") ?? ranked[0]?.sic ?? null;
  const selected = ranked.find((r: any) => r.sic === selectedSic) ?? ranked[0];
  const scaled = ranked.map((r: any) => ({ ...r, industry: industryName(r.industry, r.sic), breakdown: Object.fromEntries(
    SOURCE_KEYS.map((k) => [k, r.breakdown[k] * (100 / (SOURCE_KEYS.reduce((s, kk) => s + 25 * weights[kk], 0) || 1))])) }));

  return (
    <div>
      <PageHeader eyebrow="What's next" title="Industries where the evidence is lining up"
        subtitle="Each industry earns up to 25 points from each of four independent sources. Where several agree, something real is usually happening. Click an industry to see the companies behind it."
        right={<JobButton start="/opportunities/run" status="/opportunities/status" invalidate={[["opportunities"]]}
          label="Refresh ranking" hint="Follows the giants' deals and rebuilds the ranking (a few minutes)" />} />

      <div className="mb-6"><Callout tone="caution">
        This combined ranking isn't backtested. Its parts were tested separately with mixed results (see Track record).
        Use it to decide where to look, then read the companies' own evidence before buying anything.
      </Callout></div>

      {q.isLoading ? <LoadingCards /> : !ranked.length ? (
        <Empty title="No ranking yet">Click “Refresh ranking”. The first run takes a few minutes.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          <Card className="xl:col-span-2">
            <SourceBars rows={scaled.slice(0, 14)} selected={selected?.sic} onSelect={(sic) => setParams({ sic })} />
          </Card>
          <Card>
            <h3 className="h-section mb-1">How much each source counts</h3>
            <p className="mb-5 text-sm text-ink-3">Drag to re-weight. The ranking updates instantly.</p>
            <div className="space-y-5">
              {SOURCE_KEYS.map((k, i) => (
                <div key={k}>
                  <div className="mb-1.5 flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 font-medium text-ink"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[i] }} />{SOURCE_LABELS[k]}</span>
                    <span className="tabular text-ink-3">{weights[k].toFixed(1)}×</span>
                  </div>
                  <input type="range" min={0} max={2} step={0.1} value={weights[k]} aria-label={`${SOURCE_LABELS[k]} weight`}
                    onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} className="w-full accent-[var(--accent)]" />
                  <p className="mt-1 text-xs leading-relaxed text-ink-3">{SOURCE_HELP[k]}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {selected && (
        <Card className="mt-6" pad={false}>
          <div className="flex flex-wrap items-start justify-between gap-4 px-6 pt-6">
            <div>
              <div className="eyebrow">SIC {selected.sic}</div>
              <h2 className="mt-1 text-xl font-semibold">{industryName(selected.industry, selected.sic)}</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {SOURCE_KEYS.map((k, i) => (
                  <span key={k} className="pill border border-line bg-raised text-ink-2">
                    <span className="h-2 w-2 rounded-sm" style={{ background: SERIES[i] }} />
                    {SOURCE_LABELS[k]} <span className="tabular text-ink">{selected.breakdown[k].toFixed(1)}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="text-right"><div className="text-3xl font-semibold tabular">{selected.score.toFixed(0)}</div><div className="text-xs text-ink-3">score / 100</div></div>
          </div>
          <div className="mt-5 overflow-x-auto">
            <table className="table-base">
              <thead><tr><th>Company</th><th>Sources</th><th>Evidence</th></tr></thead>
              <tbody>
                {selected.companies.map((c: any) => (
                  <tr key={c.ticker || c.company}>
                    <td className="w-56">
                      {c.ticker ? <Link to={`/company/${c.ticker}`} className="font-semibold text-ink hover:text-accent">{c.ticker}</Link> : <span className="text-ink-3">private</span>}
                      <div className="truncate text-xs text-ink-3">{titleCase(c.company)}</div>
                    </td>
                    <td className="w-40"><Badge tone={c.source_count >= 2 ? "accent" : "neutral"}>{c.source_count} of 4</Badge></td>
                    <td>
                      <ul className="space-y-1">
                        {Object.entries(c.sources).map(([k, notes]: any) => (
                          <li key={k} className="flex gap-2 text-sm">
                            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-sm" style={{ background: SERIES[SOURCE_KEYS.indexOf(k)] }} />
                            <span><span className="text-ink-3">{SOURCE_LABELS[k]}:</span> {notes.join(" · ")}</span>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

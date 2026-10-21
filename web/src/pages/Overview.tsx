import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Sparkles } from "lucide-react";
import { apiOrNull, api } from "../lib/api";
import { industryName, pct, shortDate, titleCase, usd } from "../lib/format";
import { Badge, Card, Delta, Empty, Skeleton, Stat } from "../components/ui";
import { MiniStack } from "../components/charts";
import { TickerSearch } from "../components/Layout";

const POPULAR = ["NVDA", "MU", "VST", "CEG", "SNDK", "ANET"];

export function relationshipBadge(r: string) {
  if (r === "invested") return <Badge tone="good">Invested</Badge>;
  if (r === "announced") return <Badge tone="neutral">Announced</Badge>;
  if (r === "ipo_stake") return <span title="Held privately before; visible in the 13F only because the company went public"><Badge tone="warn">Stake after IPO</Badge></span>;
  return <Badge tone="accent">Agreement</Badge>;
}

export default function Overview() {
  const opp = useQuery({ queryKey: ["opportunities"], queryFn: () => apiOrNull("/opportunities/latest") });
  const scan = useQuery({ queryKey: ["scan"], queryFn: () => apiOrNull("/scanner/latest") });
  const funds = useQuery({ queryKey: ["institutions"], queryFn: () => apiOrNull("/institutions/latest") });
  const insiders = useQuery({ queryKey: ["insider-clusters", 90], queryFn: () => api("/insiders/clusters?days=90&min_buyers=2") });

  const industries = opp.data?.industries ?? [];
  const giants = opp.data?.giants_money ?? [];
  const invested = giants.filter((g: any) => g.relationship === "invested");
  const consensus = (funds.data?.consensus ?? []).filter((c: any) => c.ticker && c.buyer_count >= 2).slice(0, 6);
  const clusters = (insiders.data?.clusters ?? []).filter((c: any) => c.avg_per_buyer >= 50000);
  const scores = [...(scan.data?.buy_scores ?? [])].sort((a: any, b: any) => b.score - a.score).slice(0, 8);

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-3xl border border-line bg-surface px-6 py-10 sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/20 blur-3xl" />
        <div className="relative max-w-3xl">
          <Badge tone="accent"><Sparkles size={12} /> Updated from SEC filings weekly</Badge>
          <h1 className="mt-5 text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">
            Find the bottleneck <span className="text-accent">before</span> the market does.
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-ink-2 sm:text-lg">
            Chokepoint reads every 10-K, 10-Q and 8-K for signs of scarcity, follows where NVIDIA, Microsoft,
            Alphabet and Amazon put their money, tracks what top funds and insiders buy, and tests every signal
            against history.
          </p>
          <div className="mt-7 max-w-xl"><TickerSearch big /></div>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-ink-3">
            Try:
            {POPULAR.map((t) => <Link key={t} to={`/company/${t}`} className="rounded-lg border border-line px-2.5 py-1 text-ink-2 hover:border-accent/50 hover:text-ink">{t}</Link>)}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {opp.isLoading ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-32" />) : <>
          <Stat label="Top industry right now" value={<span className="text-xl leading-snug">{industries[0] ? industryName(industries[0].industry, industries[0].sic) : "—"}</span>}
            sub={industries[0] ? `${industries[0].sources_present} of 4 evidence sources agree` : "Run the ranking"} />
          <Stat label="Giants' investments, 12 mo" value={invested.length}
            sub={`${usd(invested.reduce((s: number, g: any) => s + (g.amount_usd || 0), 0))} stated across deals`} />
          <Stat label="Most-bought by top funds" value={consensus[0]?.ticker ?? "—"}
            sub={consensus[0] ? `${consensus[0].buyer_count} funds bought, ${consensus[0].new_position_count} new positions` : ""} />
          <Stat label="Insider buying clusters, 90 d" value={clusters.length}
            sub="2+ executives buying their own stock" />
        </>}
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between">
          <div>
            <h2 className="h-section">Where the money is going</h2>
            <p className="mt-1 text-sm text-ink-3">Industries ranked on four independent kinds of evidence.</p>
          </div>
          <Link to="/industries" className="link inline-flex items-center gap-1 text-sm">See all <ArrowRight size={14} /></Link>
        </div>
        {opp.isLoading ? <Skeleton className="h-48" /> : industries.length === 0 ? (
          <Empty title="No industry ranking yet">Open “What's next” and run the ranking.</Empty>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {industries.slice(0, 6).map((ind: any, i: number) => (
              <Link key={ind.sic} to={`/industries?sic=${ind.sic}`} className="card card-pad group block transition hover:border-accent/40">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="eyebrow">#{i + 1} · SIC {ind.sic}</div>
                    <div className="mt-1 line-clamp-2 font-semibold text-ink group-hover:text-accent">{industryName(ind.industry, ind.sic)}</div>
                  </div>
                  <div className="text-right"><div className="text-2xl font-semibold tabular">{ind.score.toFixed(0)}</div><div className="text-[11px] text-ink-3">score</div></div>
                </div>
                <div className="mt-4"><MiniStack breakdown={ind.breakdown} /></div>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {ind.companies.filter((c: any) => c.ticker).slice(0, 4).map((c: any) => (
                    <span key={c.ticker} className="rounded-md bg-raised px-2 py-0.5 text-xs font-medium text-ink-2">{c.ticker}</span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3" pad={false}>
          <div className="flex items-end justify-between px-6 pt-6">
            <div><h2 className="h-section">The giants' latest moves</h2>
              <p className="mt-1 text-sm text-ink-3">Investments and deals by NVIDIA, Microsoft, Alphabet, Amazon, Meta and Apple.</p></div>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="table-base">
              <thead><tr><th className="pl-6">Date</th><th>Who → into</th><th>What</th><th className="text-right">Size</th><th className="pr-6 text-right">Since</th></tr></thead>
              <tbody>
                {giants.slice(0, 9).map((g: any, i: number) => (
                  <tr key={i}>
                    <td className="whitespace-nowrap pl-6 text-ink-3">{shortDate(g.date)}</td>
                    <td><span className="font-medium text-ink">{g.giant}</span> <span className="text-ink-3">→</span>{" "}
                      {g.ticker ? <Link className="link font-medium" to={`/company/${g.ticker}`}>{g.ticker}</Link> : null}
                      <div className="max-w-[240px] truncate text-xs text-ink-3">{titleCase(g.company)}</div></td>
                    <td>{relationshipBadge(g.relationship)}</td>
                    <td className="text-right tabular">{usd(g.amount_usd)}</td>
                    <td className="pr-6 text-right"><Delta value={g.return_to_today_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {opp.isLoading && <div className="p-6"><Skeleton className="h-40" /></div>}
          </div>
        </Card>

        <Card className="xl:col-span-2" pad={false}>
          <div className="px-6 pt-6"><h2 className="h-section">Top funds' favorite buys</h2>
            <p className="mt-1 text-sm text-ink-3">Most tracked managers buying last quarter (13F), and each stock's move since that quarter ended.</p></div>
          <ul className="mt-3 divide-y divide-line">
            {consensus.map((c: any) => (
              <li key={c.cusip}>
                <Link to={`/company/${c.ticker}`} className="flex items-center gap-3 px-6 py-3 hover:bg-raised/60">
                  <span className="w-14 font-semibold text-ink">{c.ticker}</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{titleCase(c.name)}</span>
                  <span className="text-sm tabular text-ink">{c.buyer_count} <span className="text-ink-3">funds</span></span>
                  <span className="w-[76px] text-right"><Delta value={c.since_quarter_end_pct} /></span>
                </Link>
              </li>
            ))}
            {funds.isLoading && <li className="p-6"><Skeleton className="h-40" /></li>}
          </ul>
        </Card>
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between">
          <div><h2 className="h-section">Highest buy scores</h2>
            <p className="mt-1 text-sm text-ink-3">The scanner's supplier universe, scored on evidence that's been backtested.</p></div>
          <Link to="/scanner" className="link inline-flex items-center gap-1 text-sm">Scanner <ArrowRight size={14} /></Link>
        </div>
        <Card pad={false}>
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead><tr><th>Ticker</th><th>Score</th><th>Industry</th><th className="text-right">Own scarcity</th><th className="text-right">Rev growth (FY)</th><th className="text-right">Flags</th></tr></thead>
              <tbody>
                {scores.map((s: any) => (
                  <tr key={s.ticker}>
                    <td><Link to={`/company/${s.ticker}`} className="font-semibold text-ink hover:text-accent">{s.ticker}</Link></td>
                    <td className="w-48"><div className="flex items-center gap-2.5"><div className="h-1.5 w-24 rounded-full bg-raised"><div className="h-full rounded-full bg-accent" style={{ width: `${s.score}%` }} /></div><span className="tabular text-ink">{s.score}</span></div></td>
                    <td className="max-w-[260px] truncate">{s.industry_label}</td>
                    <td className="text-right tabular">{s.own_tightness?.mentions ?? "—"}</td>
                    <td className="text-right tabular">{pct(s.valuation?.revenue_growth_annual, 0)}</td>
                    <td className="text-right tabular">{s.caution_flags?.length ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {scan.isLoading && <div className="p-6"><Skeleton className="h-40" /></div>}
          </div>
        </Card>
      </section>
    </div>
  );
}

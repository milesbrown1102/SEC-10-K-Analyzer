import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ExternalLink, Loader2, XCircle } from "lucide-react";
import clsx from "clsx";
import { api, apiOrNull, post } from "../lib/api";
import { industryName, pct, price, shortDate, titleCase, usd } from "../lib/format";

function addedLabel(p: number | null) {
  if (p === null || p === undefined) return "Added";
  return p >= 300 ? `Added ${(p / 100 + 1).toFixed(0)}×` : `Added ${pct(p, 0)}`;
}
import { Badge, Callout, Card, Delta, Empty, ErrorNote, Skeleton } from "../components/ui";
import { PriceChart, ScoreRing } from "../components/charts";
import { relationshipBadge } from "./Overview";

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-raised/40 px-4 py-3">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular text-ink">{value}</div>
      {sub && <div className="text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

const CHANGE_TONE: Record<string, "good" | "accent" | "neutral" | "warn" | "bad"> = {
  new: "good", added: "accent", held: "neutral", trimmed: "warn", exited: "bad",
};

export default function Company() {
  const { ticker = "" } = useParams();
  const t = ticker.toUpperCase();
  const prof = useQuery({ queryKey: ["profile", t], queryFn: () => api(`/company/${t}/profile`) });
  const scan = useQuery({ queryKey: ["scan"], queryFn: () => apiOrNull("/scanner/latest") });
  const evidence = scan.data?.score_evidence?.factors ?? {};

  if (prof.isLoading) return (
    <div className="space-y-6"><Skeleton className="h-28" /><div className="grid gap-6 lg:grid-cols-3"><Skeleton className="h-80 lg:col-span-2" /><Skeleton className="h-80" /></div><Skeleton className="h-64" /></div>
  );
  if (prof.error) return <ErrorNote error={prof.error} />;
  const p = prof.data;
  const v = p.valuation || {};
  const ps = v.sales_yield ? 1 / v.sales_yield : null;
  const pe = v.earnings_yield && v.earnings_yield > 0 ? 1 / v.earnings_yield : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="eyebrow">{p.industry ? industryName(p.industry, p.sic) : "Company"}</div>
          <h1 className="mt-1 flex flex-wrap items-baseline gap-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            {t}<span className="text-xl font-normal text-ink-2 sm:text-2xl">{titleCase(p.name)}</span>
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span className="text-2xl font-semibold tabular">{price(p.stock.price)}</span>
            <Delta value={p.stock.return_1y_pct} label="1 yr" size="md" />
            {p.stock.spy_1y_pct !== null && <span className="text-sm text-ink-3">S&P 500 {pct(p.stock.spy_1y_pct)} same year</span>}
            {p.stock.above_200sma === true && <Badge tone="good">Uptrend</Badge>}
            {p.stock.above_200sma === false && <Badge tone="bad">Downtrend</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <ScoreRing score={p.score.score} />
          <div className="max-w-[180px] text-sm text-ink-3">Buy score from evidence that's been backtested. <a href="#score" className="link">Breakdown</a></div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="flex flex-col lg:col-span-2"><PriceChart ticker={t} tall /></Card>
        <Card>
          <h2 className="h-section">What it does</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">{p.description?.summary || "No business description found in its filings."}</p>
          {p.description?.url && <a href={p.description.url} target="_blank" rel="noreferrer" className="link mt-2 inline-flex items-center gap-1 text-xs">From its {p.description.source} <ExternalLink size={11} /></a>}
          <div className="mt-5 grid grid-cols-2 gap-3">
            <Metric label="Market value" value={usd(v.market_cap)} />
            <Metric label="Price / sales" value={ps ? `${ps.toFixed(1)}×` : "—"} />
            <Metric label="Price / earnings" value={pe ? `${pe.toFixed(0)}×` : v.earnings_yield < 0 ? "loss" : "—"} />
            <Metric label="Revenue growth" value={pct(p.quarterly_revenue_growth_pct, 0)} sub="latest quarter, YoY" />
          </div>
        </Card>
      </div>

      {/* Case for / against */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card>
          <h2 className="h-section flex items-center gap-2"><CheckCircle2 size={18} className="text-good" /> The case for</h2>
          <ul className="mt-4 space-y-3">
            {p.case.for.length ? p.case.for.map((x: string, i: number) => (
              <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-ink-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-good" />{x}</li>
            )) : <li className="text-sm text-ink-3">No supporting evidence found.</li>}
          </ul>
        </Card>
        <Card>
          <h2 className="h-section flex items-center gap-2"><XCircle size={18} className="text-bad" /> The case against</h2>
          <ul className="mt-4 space-y-3">
            {p.case.against.length ? p.case.against.map((x: string, i: number) => (
              <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-ink-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-bad" />{x}</li>
            )) : <li className="text-sm text-ink-3">No red flags in the data checked. That doesn't mean there aren't any.</li>}
          </ul>
        </Card>
      </div>
      <p className="-mt-2 text-xs text-ink-3">Both lists are generated by fixed rules from the data on this page. They're research input, not a recommendation.</p>

      {/* Smart money */}
      <Card pad={false}>
        <div className="px-6 pt-6">
          <h2 className="h-section">Smart money</h2>
          <p className="mt-1 text-sm text-ink-3">
            Tracked funds' latest 13F moves. A 13F shows holdings at quarter end, so a purchase happened sometime in that quarter.
            The price range shows roughly what they paid. Funds don't disclose why they buy.
          </p>
        </div>
        {p.funds.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="table-base">
              <thead><tr><th>Fund</th><th>Move</th><th>Bought during</th><th>Price range then</th><th className="text-right">Now vs their avg</th><th className="text-right">Portfolio weight</th></tr></thead>
              <tbody>
                {p.funds.map((f: any, i: number) => (
                  <tr key={i}>
                    <td><div className="font-medium text-ink">{f.manager}</div><div className="text-xs text-ink-3">{f.person}</div></td>
                    <td><Badge tone={CHANGE_TONE[f.change]}>{f.change === "new" ? "New position" : f.change === "added" ? addedLabel(f.shares_change_pct) : titleCase(f.change)}</Badge></td>
                    <td className="whitespace-nowrap">{shortDate(f.window_start)} – {shortDate(f.window_end)}
                      {f.price_range?.first_trading_day && <div className="text-xs text-ink-3">IPO'd {shortDate(f.price_range.first_trading_day)}</div>}</td>
                    <td className="whitespace-nowrap tabular">{f.price_range ? `${price(f.price_range.low)} – ${price(f.price_range.high)}` : "—"}
                      {f.price_range && <div className="text-xs text-ink-3">avg {price(f.price_range.avg)}</div>}</td>
                    <td className="text-right"><Delta value={f.since_avg_pct} /></td>
                    <td className="text-right tabular">{f.weight_pct?.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="px-6 pb-6 pt-3 text-sm text-ink-3">None of the 18 tracked funds held or traded it last quarter.</p>}

        <div className="border-t border-line px-6 pb-6 pt-5">
          <h3 className="text-sm font-semibold text-ink">Insiders buying with their own money (last 12 months)</h3>
          {p.insider_year?.rows?.length ? (
            <div className="mt-3 overflow-x-auto">
              <table className="table-base">
                <thead><tr><th>Filed</th><th>Insider</th><th>Role</th><th className="text-right">Shares</th><th className="text-right">Price</th><th className="text-right">Value</th><th>Plan</th></tr></thead>
                <tbody>{p.insider_year.rows.map((r: any, i: number) => (
                  <tr key={i}><td className="whitespace-nowrap">{shortDate(r.filing_date)}</td><td className="text-ink">{titleCase(r.owner_name)}</td>
                    <td>{r.title || r.relationship}</td><td className="text-right tabular">{Math.round(r.shares).toLocaleString()}</td>
                    <td className="text-right tabular">{price(r.price)}</td><td className="text-right tabular">{usd(r.value)}</td>
                    <td>{r.plan_10b5_1 ? <Badge>Pre-set plan</Badge> : <Badge tone="good">Discretionary</Badge>}</td></tr>
                ))}</tbody>
              </table>
            </div>
          ) : <p className="mt-2 text-sm text-ink-3">No officer or director open-market purchases in the last year.</p>}
        </div>
      </Card>

      {/* Connections */}
      {(p.connections.giants.length > 0 || p.connections.own_deals.length > 0) && (
        <Card>
          <h2 className="h-section">Connections</h2>
          <p className="mt-1 text-sm text-ink-3">Mega-caps that invested in or signed with it, and its own recent agreements.</p>
          <ul className="mt-4 space-y-3">
            {p.connections.giants.map((g: any, i: number) => (
              <li key={i} className="flex flex-wrap items-center gap-3 text-sm">
                {relationshipBadge(g.relationship)}<span className="font-medium text-ink">{g.giant}</span>
                <span className="text-ink-3">{shortDate(g.date)}</span>{g.amount_usd && <span className="tabular text-ink-2">{usd(g.amount_usd)}</span>}
                {g.url && <a href={g.url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">filing <ExternalLink size={11} /></a>}
              </li>
            ))}
            {p.connections.own_deals.map((d: any, i: number) => (
              <li key={`o${i}`} className="text-sm text-ink-2"><Badge>{d.type.replace("_", " ")}</Badge> <span className="text-ink-3">{shortDate(d.date)}</span>
                {d.counterparty && <> with <span className="text-ink">{d.counterparty}</span></>} — {d.evidence?.slice(0, 220)}…</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Score breakdown */}
      <Card>
        <div id="score" className="flex flex-wrap items-end justify-between gap-3">
          <div><h2 className="h-section">Score breakdown</h2>
            <p className="mt-1 text-sm text-ink-3">Every point traces to data. "Backtest IC" shows how well each factor predicted relative returns in 2017–2026 (0 = no value; |t| under 2 = noise).</p></div>
          <Link to="/track-record" className="link text-sm">How the score is tested</Link>
        </div>
        <div className="mt-4 divide-y divide-line">
          {p.score.breakdown.map((b: any) => {
            const ev = evidence[b.key];
            return (
              <div key={b.key} className="grid grid-cols-1 gap-2 py-3 sm:grid-cols-[170px_1fr_190px] sm:items-center">
                <div className="flex items-center gap-3">
                  <span className="w-14 tabular text-sm font-semibold text-ink">{b.max ? `+${b.points}/${b.max}` : "info"}</span>
                  <div className="h-1.5 w-20 rounded-full bg-raised"><div className="h-full rounded-full bg-accent" style={{ width: b.max ? `${(b.points / b.max) * 100}%` : 0 }} /></div>
                </div>
                <div><div className="text-sm font-medium text-ink">{b.factor}</div><div className="text-xs leading-relaxed text-ink-3">{b.why}</div></div>
                <div className="whitespace-nowrap text-xs text-ink-3 sm:text-right">{ev?.mean_ic != null ? <>Backtest IC <span className="tabular text-ink-2">{ev.mean_ic >= 0 ? "+" : ""}{ev.mean_ic.toFixed(2)}</span> (t {ev.t_stat})</> : "not backtested"}</div>
              </div>
            );
          })}
        </div>
      </Card>

      <FilingHistory ticker={t} />
    </div>
  );
}

// -----------------------------------------------------------------------------
// Filing history + what happened next
// -----------------------------------------------------------------------------

function FilingHistory({ ticker }: { ticker: string }) {
  const qc = useQueryClient();
  const stored = useQuery({ queryKey: ["historical", ticker], queryFn: () => apiOrNull(`/historical/${ticker}`) });
  const run = useMutation({
    mutationFn: () => post(`/historical/run`, { ticker, max_years: 6 }),
    onSuccess: (data) => qc.setQueryData(["historical", ticker], data),
  });
  const data = stored.data;
  const filings: string[] = data ? Array.from(new Set<string>([...(data.filings ?? []), ...data.signal_trend.map((s: any) => s.fiscal_year_end)])).sort().reverse() : [];

  return (
    <Card>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="h-section">Filing history & what happened next</h2>
          <p className="mt-1 max-w-3xl text-sm text-ink-3">What each annual report flagged, then over the next 12 months: how the stock did, who it put money into (and how their stocks did, and why), and what it built itself.</p>
        </div>
        <button className="btn-ghost" disabled={run.isPending} onClick={() => run.mutate()}>
          {run.isPending && <Loader2 size={15} className="animate-spin" />}{run.isPending ? "Reading 6 years of 10-Ks…" : data ? "Re-analyze" : "Analyze 6 years of filings"}
        </button>
      </div>
      {run.error && <div className="mt-4"><ErrorNote error={run.error} /></div>}
      {!data && !run.isPending && <div className="mt-5"><Empty title="Not analyzed yet">Reads its last six 10-Ks for bottleneck language (under a minute once cached).</Empty></div>}
      <div className="mt-5 space-y-3">
        {filings.map((fd) => <FilingRow key={fd} ticker={ticker} filingDate={fd} signals={data.signal_trend.filter((s: any) => s.fiscal_year_end === fd)} />)}
      </div>
    </Card>
  );
}

function FilingRow({ ticker, filingDate, signals }: { ticker: string; filingDate: string; signals: any[] }) {
  const [open, setOpen] = useState(false);
  const am = useQuery({ queryKey: ["aftermath", ticker, filingDate], queryFn: () => api(`/historical/${ticker}/aftermath?filing_date=${filingDate}`), enabled: open, staleTime: Infinity });
  return (
    <div className="rounded-xl border border-line">
      <button className="flex w-full flex-wrap items-center gap-3 px-4 py-3.5 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="font-semibold text-ink">10-K · {shortDate(filingDate)}</span>
        <div className="flex flex-1 flex-wrap gap-1.5">
          {signals.length ? signals.sort((a, b) => b.confidence - a.confidence).map((s) => <Badge key={s.category}>{s.category} {Math.round(s.confidence * 100)}%</Badge>)
            : <span className="text-sm text-ink-3">No bottleneck language</span>}
        </div>
        <span className="flex items-center gap-1 text-sm text-accent">What happened next <ChevronDown size={16} className={clsx("transition", open && "rotate-180")} /></span>
      </button>
      {open && (
        <div className="border-t border-line px-4 py-5">
          {signals.length > 0 && (
            <details className="mb-5"><summary className="cursor-pointer text-sm text-ink-3">What the filing said</summary>
              <ul className="mt-3 space-y-2">{signals.map((s) => <li key={s.category} className="text-sm text-ink-2"><span className="font-medium text-ink">{s.category}:</span> “{s.evidence}”</li>)}</ul>
            </details>
          )}
          {am.isLoading ? <div className="flex items-center gap-2 text-sm text-ink-3"><Loader2 size={15} className="animate-spin" /> Reading the 12 months after this filing (up to a couple of minutes the first time)…</div>
            : am.error ? <ErrorNote error={am.error} /> : am.data && <Aftermath am={am.data} />}
        </div>
      )}
    </div>
  );
}

function Aftermath({ am }: { am: any }) {
  const s = am.stock;
  return (
    <div className="space-y-6">
      {!am.window_complete && <Callout>Less than 12 months have passed. Showing what's happened up to {shortDate(am.window_end)}.</Callout>}
      <div>
        <h4 className="eyebrow mb-3">The stock afterwards</h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(["3m", "6m", "12m"] as const).map((h) => (
            <div key={h} className="rounded-xl border border-line bg-raised/40 px-4 py-3">
              <div className="text-xs text-ink-3">{h.replace("m", "")} months later</div>
              <div className="mt-1 text-lg font-semibold tabular">{pct(s[h]?.return_pct)}</div>
              {s[h]?.vs_spy_pct != null && <Delta value={s[h].vs_spy_pct} suffix=" pts" label="vs S&P" />}
            </div>
          ))}
          <div className="rounded-xl border border-line bg-raised/40 px-4 py-3">
            <div className="text-xs text-ink-3">Filing → today</div>
            <div className="mt-1 text-lg font-semibold tabular">{pct(s.to_today?.return_pct)}</div>
            <div className="text-xs text-ink-3">S&P {pct(s.to_today?.spy_pct)}</div>
          </div>
        </div>
      </div>

      <div>
        <h4 className="eyebrow mb-3">Money into, and deals with, other companies</h4>
        {am.deal_patterns?.notes?.map((n: string, i: number) => <div key={i} className="mb-3"><Callout>{n}</Callout></div>)}
        {am.counterparty_deals.length ? (
          <div className="space-y-2">
            {am.counterparty_deals.map((d: any, i: number) => <DealRow key={i} d={d} />)}
          </div>
        ) : <p className="text-sm text-ink-3">No other company's filing or press release named it as investor or partner in this period.</p>}
      </div>

      {am.thirteen_f?.positions?.length > 0 && (
        <div>
          <h4 className="eyebrow mb-3">New stakes in public companies (its own 13F)</h4>
          <div className="overflow-x-auto"><table className="table-base">
            <thead><tr><th>Company</th><th>Industry</th><th className="text-right">Position</th><th className="text-right">Next 12 m</th><th className="text-right">To today</th></tr></thead>
            <tbody>{am.thirteen_f.positions.map((x: any, i: number) => (
              <tr key={i}><td>{x.ticker ? <Link className="link" to={`/company/${x.ticker}`}>{x.ticker}</Link> : "—"} <span className="text-xs text-ink-3">{titleCase(x.company)}</span></td>
                <td>{titleCase(x.industry)}</td><td className="text-right tabular">{usd(x.value)}</td>
                <td className="text-right"><Delta value={x.return_12m_pct} /></td><td className="text-right"><Delta value={x.return_to_today_pct} /></td></tr>
            ))}</tbody></table></div>
        </div>
      )}

      <div>
        <h4 className="eyebrow mb-3">What it built or secured itself</h4>
        {am.capex?.change_pct != null && <p className="mb-3 text-sm text-ink-2">Capital spending: {usd(am.capex.before_usd)} → {usd(am.capex.after_usd)} <Delta value={am.capex.change_pct} digits={0} /></p>}
        {[...am.disclosed.in_house.map((x: any) => ({ ...x, kind: "Built in-house" })), ...am.disclosed.secured_supply.map((x: any) => ({ ...x, kind: "Secured by contract" }))].map((x: any, i: number) => (
          <blockquote key={i} className="mb-2 border-l-2 border-accent/50 pl-3 text-sm text-ink-2">“{x.sentence}” <span className="text-xs text-ink-3">— {x.kind}, {x.form} {shortDate(x.date)}</span></blockquote>
        ))}
        {!am.disclosed.in_house.length && !am.disclosed.secured_supply.length && <p className="text-sm text-ink-3">No in-house or secured-supply statements in its filings from this period.</p>}
      </div>
    </div>
  );
}

function DealRow({ d }: { d: any }) {
  const [open, setOpen] = useState(false);
  const r = d.return_12m_pct ?? d.return_to_today_pct;
  return (
    <div className="rounded-xl border border-line bg-raised/30">
      <button className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left sm:grid-cols-[110px_auto_1fr_110px_110px_24px]" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="hidden text-sm text-ink-3 sm:block">{shortDate(d.date)}</span>
        {relationshipBadge(d.relationship)}
        <span className="min-w-0 truncate text-sm"><span className="font-medium text-ink">{d.ticker || "Private"}</span> <span className="text-ink-3">{titleCase(d.company)} · {titleCase(d.industry)}</span></span>
        <span className="hidden text-right text-sm tabular text-ink-2 sm:block">{usd(d.amount_usd)}</span>
        <span className="text-right"><Delta value={r} /></span>
        <ChevronDown size={16} className={clsx("hidden text-ink-3 transition sm:block", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-line px-4 py-4 text-sm">
          {d.why?.reasons?.length ? (
            <div><div className="mb-2 font-medium text-ink">Why the stock moved</div>
              <ul className="space-y-1.5">{d.why.reasons.map((x: string, i: number) => <li key={i} className="flex gap-2 text-ink-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />{x}</li>)}</ul></div>
          ) : <p className="text-ink-3">No price data to explain the move (private or recently listed).</p>}
          <div className="text-ink-3"><span className="font-medium text-ink-2">From the filing:</span> “{d.evidence}”</div>
          {d.amount_sentence && <div className="text-xs text-ink-3">Amount from: “{d.amount_sentence}”</div>}
          <div className="flex gap-4">{d.ticker && <Link to={`/company/${d.ticker}`} className="link">Open {d.ticker}</Link>}
            <a href={d.url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">Read the filing <ExternalLink size={12} /></a></div>
        </div>
      )}
    </div>
  );
}

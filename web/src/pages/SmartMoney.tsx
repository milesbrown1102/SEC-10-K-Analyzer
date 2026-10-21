import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, apiOrNull } from "../lib/api";
import { pct, shortDate, titleCase, usd } from "../lib/format";
import { Badge, Callout, Card, Delta, Empty, JobButton, LoadingCards, PageHeader, Tabs } from "../components/ui";

type Tab = "consensus" | "funds" | "insiders";

export default function SmartMoney() {
  const [tab, setTab] = useState<Tab>("consensus");
  const rep = useQuery({ queryKey: ["institutions"], queryFn: () => apiOrNull("/institutions/latest") });
  const managers = (rep.data?.managers ?? []).filter((m: any) => !m.error);
  const quarter = managers.length ? managers.map((m: any) => m.report_date).sort().reverse()[0] : null;
  const prior = managers.find((m: any) => m.report_date === quarter)?.prior_report_date;

  return (
    <div>
      <PageHeader eyebrow="Smart money" title="What top investors and insiders are buying"
        subtitle={<>13F holdings from {managers.length} well-known funds{quarter ? <> for the quarter <b className="text-ink">{shortDate(prior)} – {shortDate(quarter)}</b></> : ""}, plus executives buying their own stock (Form 4). Open any company to see the price range they likely paid and the case for and against.</>}
        right={<JobButton start="/institutions/refresh" status="/institutions/status" invalidate={[["institutions"]]} label="Refresh 13F data" />} />
      <div className="mb-6"><Callout tone="caution">13Fs arrive up to 45 days after quarter end and show only long US stock positions, so these purchases may already be weeks or months old. Funds don't say why they buy.</Callout></div>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "consensus", label: "Most-bought" }, { id: "funds", label: "By fund" }, { id: "insiders", label: "Insider buying" }]} />
      {rep.isLoading ? <LoadingCards /> : !rep.data ? <Empty title="No 13F data yet">Click “Refresh 13F data” (a few minutes the first time).</Empty> :
        tab === "consensus" ? <Consensus rows={rep.data.consensus} /> : tab === "funds" ? <ByFund managers={managers} /> : <Insiders />}
    </div>
  );
}

function Consensus({ rows }: { rows: any[] }) {
  const [min, setMin] = useState(2);
  const list = rows.filter((r) => r.buyer_count >= min);
  return (
    <Card pad={false}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-6">
        <p className="text-sm text-ink-3">A <b className="text-ink-2">buyer</b> opened a position or grew it 10%+; a <b className="text-ink-2">seller</b> cut 10%+ or exited. Options excluded.</p>
        <label className="flex items-center gap-2 text-sm text-ink-3">At least
          <select value={min} onChange={(e) => setMin(Number(e.target.value))} className="rounded-lg border border-line bg-raised px-2 py-1 text-ink">
            {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select> buyers</label>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="table-base">
          <thead><tr><th>Company</th><th className="text-right">Buyers</th><th className="text-right">New</th><th className="text-right">Sellers</th><th className="text-right">Est. net flow</th><th className="text-right" title="Price change since the end of the quarter they bought in">Since quarter end</th><th>Bought by</th></tr></thead>
          <tbody>{list.slice(0, 150).map((r) => (
            <tr key={r.cusip}>
              <td className="w-64">{r.ticker ? <Link to={`/company/${r.ticker}`} className="font-semibold text-ink hover:text-accent">{r.ticker}</Link> : <span className="text-ink-3">—</span>}
                <div className="truncate text-xs text-ink-3">{titleCase(r.name)}</div></td>
              <td className="text-right tabular text-ink">{r.buyer_count}</td>
              <td className="text-right tabular">{r.new_position_count}</td>
              <td className="text-right tabular">{r.seller_count}</td>
              <td className="text-right tabular">{usd(r.est_net_value_change)}</td>
              <td className="text-right"><Delta value={r.since_quarter_end_pct} /></td>
              <td className="max-w-md text-xs leading-relaxed">{r.buyers.map((b: any) => b.manager).join(", ")}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </Card>
  );
}

function ByFund({ managers }: { managers: any[] }) {
  const [i, setI] = useState(0);
  const m = managers[i];
  const moves = m.changes.filter((c: any) => !c.put_call);
  const buys = moves.filter((c: any) => c.change_type === "new" || c.change_type === "added").slice(0, 25);
  const sells = moves.filter((c: any) => c.change_type === "trimmed" || c.change_type === "exited").slice(0, 25);
  const Table = ({ rows }: { rows: any[] }) => (
    <table className="table-base"><thead><tr><th>Company</th><th>Move</th><th className="text-right">Weight now</th><th className="text-right">Est. $</th></tr></thead>
      <tbody>{rows.map((c, k) => (
        <tr key={k}><td>{c.ticker ? <Link to={`/company/${c.ticker}`} className="font-medium text-ink hover:text-accent">{c.ticker}</Link> : "—"} <span className="text-xs text-ink-3">{titleCase(c.name)}</span></td>
          <td>{c.change_type === "new" ? <Badge tone="good">New</Badge> : c.change_type === "exited" ? <Badge tone="bad">Exited</Badge> : <span className="tabular">{pct(c.shares_change_pct, 0)}</span>}</td>
          <td className="text-right tabular">{c.weight_curr_pct.toFixed(2)}%</td><td className="text-right tabular">{usd(c.est_value_change)}</td></tr>))}</tbody></table>
  );
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[260px_1fr]">
      <Card pad={false} className="max-h-[70vh] overflow-y-auto">
        {managers.map((x, k) => (
          <button key={x.cik} onClick={() => setI(k)} className={`block w-full border-b border-line px-4 py-3 text-left ${k === i ? "bg-raised" : "hover:bg-raised/50"}`}>
            <div className="text-sm font-medium text-ink">{x.name}</div><div className="text-xs text-ink-3">{x.manager} · {x.style}</div>
          </button>))}
      </Card>
      <div className="space-y-6">
        <Card><div className="flex flex-wrap items-baseline justify-between gap-3"><h2 className="text-xl font-semibold">{m.name}</h2>
          <span className="text-sm text-ink-3">{usd(m.total_value)} · {m.position_count} positions · quarter to {shortDate(m.report_date)}</span></div></Card>
        <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
          <Card pad={false}><div className="px-6 pt-5 h-section">Bought & added</div><div className="mt-2 overflow-x-auto"><Table rows={buys} /></div></Card>
          <Card pad={false}><div className="px-6 pt-5 h-section">Trimmed & sold</div><div className="mt-2 overflow-x-auto"><Table rows={sells} /></div></Card>
        </div>
      </div>
    </div>
  );
}

function Insiders() {
  const [days, setDays] = useState(90);
  const [minAvg, setMinAvg] = useState(50000);
  const q = useQuery({ queryKey: ["insider-clusters", days], queryFn: () => api(`/insiders/clusters?days=${days}&min_buyers=2`) });
  const rows = (q.data?.clusters ?? []).filter((c: any) => c.avg_per_buyer >= minAvg);
  return (
    <Card pad={false}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-6">
        <p className="max-w-2xl text-sm text-ink-3">Two or more officers or directors buying on the open market with their own money. Insiders sell for many reasons but buy for essentially one.</p>
        <div className="flex gap-3 text-sm">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-lg border border-line bg-raised px-2 py-1 text-ink">
            {[30, 90, 180, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select>
          <select value={minAvg} onChange={(e) => setMinAvg(Number(e.target.value))} className="rounded-lg border border-line bg-raised px-2 py-1 text-ink">
            {[0, 25000, 50000, 100000, 250000].map((v) => <option key={v} value={v}>Avg ≥ {usd(v, 0)}</option>)}</select>
        </div>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="table-base"><thead><tr><th>Company</th><th className="text-right">Insiders</th><th className="text-right">Discretionary</th><th className="text-right">Total</th><th className="text-right">Avg each</th><th>Latest</th><th>Who</th></tr></thead>
          <tbody>{rows.map((c: any) => (
            <tr key={c.issuer_cik}><td><Link to={`/company/${c.ticker}`} className="font-semibold text-ink hover:text-accent">{c.ticker}</Link><div className="text-xs text-ink-3">{titleCase(c.issuer_name)}</div></td>
              <td className="text-right tabular text-ink">{c.buyers}</td><td className="text-right tabular">{c.discretionary_buyers}</td>
              <td className="text-right tabular">{usd(c.total_value)}</td><td className="text-right tabular">{usd(c.avg_per_buyer)}</td>
              <td className="whitespace-nowrap">{shortDate(c.latest_filing)}</td><td className="max-w-xs text-xs">{c.titles.join(", ")}</td></tr>))}</tbody></table>
      </div>
    </Card>
  );
}

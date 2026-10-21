import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiOrNull } from "../lib/api";
import { shortDate, titleCase } from "../lib/format";
import { Badge, Callout, Card, Empty, JobButton, LoadingCards, PageHeader, Tabs } from "../components/ui";
import { Legend } from "../components/charts";

type Side = "seller" | "buyer";
const isFin = (sic: string) => /^\d+$/.test(sic || "") && +sic >= 6000 && +sic <= 6799;

export default function Radar() {
  const [side, setSide] = useState<Side>("seller");
  const q = useQuery({ queryKey: ["radar"], queryFn: () => apiOrNull("/radar/latest") });
  const d = q.data?.[side];
  const inds = (d?.industries ?? []).filter((r: any) => !isFin(r.sic));
  const top = inds.slice(0, 12).map((r: any) => ({ name: titleCase(r.industry), now: r.companies_now, before: r.companies_prior, change: r.change }));
  const companies = (d?.companies ?? []).filter((c: any) => c.new && c.ticker && !isFin(c.sic)).slice(0, 80);
  return (
    <div>
      <PageHeader eyebrow="Scarcity radar" title="Who's newly saying supply is tight"
        subtitle="Every 10-K and 10-Q filed with the SEC in the last 12 months vs the 12 before, searched for scarcity language. The change by industry is the signal; boilerplate appears in both years and cancels out."
        right={<JobButton start="/radar/run" status="/radar/status" invalidate={[["radar"]]} label="Re-run radar" />} />
      <Tabs<Side> value={side} onChange={setSide} tabs={[{ id: "seller", label: "Their product is scarce" }, { id: "buyer", label: "Their inputs are scarce" }]} />
      <div className="mb-6"><Callout>{side === "seller"
        ? "Seller-side: companies saying demand exceeds their supply, pricing power, record backlog. Candidates for pricing power themselves."
        : "Buyer-side: companies that can't get inputs (lead times, shortages, power availability). The bottleneck is upstream, at their suppliers."}</Callout></div>
      {q.isLoading ? <LoadingCards /> : !d ? <Empty title="No radar run yet">Click “Re-run radar” (about a minute).</Empty> : (
        <div className="space-y-6">
          <Card>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="h-section">Industries with the biggest increase</h2>
              <Legend items={[{ label: "Year before", color: "var(--ink-3)" }, { label: "Last 12 months", color: "var(--s1)" }]} />
            </div>
            <div style={{ height: Math.max(260, top.length * 38) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={top} layout="vertical" margin={{ left: 0, right: 16 }} barGap={2} barCategoryGap={10}>
                  <CartesianGrid stroke="var(--grid)" horizontal={false} />
                  <XAxis type="number" stroke="var(--axis)" tick={{ fill: "var(--ink-3)", fontSize: 12 }} tickLine={false} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={240} stroke="var(--axis)" axisLine={false} tickLine={false}
                    tick={{ fill: "var(--ink-2)", fontSize: 12.5 }} tickFormatter={(v: string) => (v.length > 36 ? v.slice(0, 35) + "…" : v)} />
                  <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} contentStyle={{ background: "var(--raised)", border: "1px solid var(--line)", borderRadius: 12, color: "var(--ink)" }} />
                  <Bar dataKey="before" name="Year before" fill="var(--ink-3)" radius={[0, 4, 4, 0]} isAnimationActive={false} />
                  <Bar dataKey="now" name="Last 12 months" fill="var(--s1)" radius={[0, 4, 4, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card pad={false}>
            <div className="px-6 pt-6"><h2 className="h-section">Companies newly using this language</h2>
              <p className="mt-1 text-sm text-ink-3">Phrase matches. Open a company to run the full sentence-level check on its latest filing.</p></div>
            <div className="mt-4 overflow-x-auto"><table className="table-base">
              <thead><tr><th>Company</th><th>Industry</th><th>Phrases</th><th>Latest filing</th></tr></thead>
              <tbody>{companies.map((c: any) => (
                <tr key={c.cik}><td><Link to={`/company/${c.ticker}`} className="font-semibold text-ink hover:text-accent">{c.ticker}</Link><div className="text-xs text-ink-3">{titleCase(c.name)}</div></td>
                  <td className="max-w-[220px] text-xs">{titleCase(c.industry)}</td>
                  <td><div className="flex flex-wrap gap-1">{c.phrases.map((p: string) => <Badge key={p}>“{p}”</Badge>)}</div></td>
                  <td className="whitespace-nowrap"><a href={c.url} target="_blank" rel="noreferrer" className="link">{c.latest_form} {shortDate(c.latest_date)}</a></td></tr>))}</tbody></table></div>
          </Card>
        </div>
      )}
    </div>
  );
}

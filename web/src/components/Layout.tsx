import { ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, Building2, Compass, FlaskConical, LayoutDashboard, Menu, Radar, Search, Users, X,
} from "lucide-react";
import { api } from "../lib/api";
import { BRAND } from "../lib/format";
import { Disclaimer } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/industries", label: "What's next", icon: Compass },
  { to: "/smart-money", label: "Smart money", icon: Users },
  { to: "/radar", label: "Scarcity radar", icon: Radar },
  { to: "/scanner", label: "Bottleneck scanner", icon: Activity },
  { to: "/track-record", label: "Track record", icon: FlaskConical },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent">
        <svg viewBox="0 0 32 32" className="h-5 w-5" aria-hidden><path d="M3 25 L12 11 L16.5 17.5 L19.5 13.5 L29 25 Z" fill="white" /><path d="M12 11 V4.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" /><path d="M12 4.5 L18.5 6.75 L12 9 Z" fill="white" /></svg>
      </div>
      <span className="text-[17px] font-semibold tracking-tight">{BRAND}</span>
    </div>
  );
}

export function TickerSearch({ autoFocus, onDone, big }: { autoFocus?: boolean; onDone?: () => void; big?: boolean }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const nav = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const results = useQuery({
    queryKey: ["search", q],
    queryFn: () => api<{ ticker: string; name: string }[]>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length > 0,
    staleTime: 60 * 60_000,
  });
  useEffect(() => {
    const h = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const go = (t: string) => { setQ(""); setOpen(false); onDone?.(); nav(`/company/${t}`); };
  const items = results.data || [];
  return (
    <div ref={box} className="relative w-full">
      <Search size={big ? 20 : 16} className={clsx("pointer-events-none absolute top-1/2 -translate-y-1/2 text-ink-3", big ? "left-4" : "left-3")} />
      <input
        autoFocus={autoFocus}
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          if (e.key === "Enter") { const t = items[active]?.ticker || q.trim().toUpperCase(); if (t) go(t); }
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder="Search any company or ticker…"
        aria-label="Search companies"
        className={clsx("w-full rounded-xl border border-line bg-surface text-ink placeholder:text-ink-3 outline-none transition focus:border-accent/60 focus:ring-4 focus:ring-accent/15",
          big ? "h-14 pl-12 pr-4 text-base" : "h-10 pl-9 pr-3 text-sm")}
      />
      {open && q && items.length > 0 && (
        <div className="absolute z-30 mt-2 w-full overflow-hidden rounded-xl border border-line bg-raised shadow-card">
          {items.map((r, i) => (
            <button key={r.ticker} onMouseEnter={() => setActive(i)} onClick={() => go(r.ticker)}
              className={clsx("flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm", i === active && "bg-surface")}>
              <span className="w-16 font-semibold text-ink">{r.ticker}</span>
              <span className="truncate text-ink-2">{r.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)}
          className={({ isActive }) => clsx("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
            isActive ? "bg-raised text-ink" : "text-ink-3 hover:bg-raised/60 hover:text-ink")}>
          <Icon size={18} />{label}
        </NavLink>
      ))}
    </nav>
  );
  return (
    <div className="min-h-full">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-line bg-page px-4 py-6 lg:flex">
        <div className="px-2"><Logo /></div>
        <div className="mt-8">{nav}</div>
        <div className="mt-auto rounded-xl border border-line bg-surface p-4 text-xs leading-relaxed text-ink-3">
          <Building2 size={16} className="mb-2 text-ink-2" />
          Built on public SEC filings: 10-K, 10-Q, 8-K, 13F and Form 4. Every signal links to its source.
        </div>
      </aside>

      <header className="sticky top-0 z-10 border-b border-line bg-page/85 backdrop-blur lg:ml-64">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <button className="btn-ghost px-2.5 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={18} /></button>
          <div className="lg:hidden"><Logo /></div>
          <div className="ml-auto w-full max-w-md"><TickerSearch /></div>
        </div>
      </header>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setMobileOpen(false)}>
          <div className="h-full w-72 bg-page p-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between"><Logo />
              <button className="btn-ghost px-2" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X size={18} /></button>
            </div>
            {nav}
          </div>
        </div>
      )}

      <main className="lg:ml-64">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">{children}</div>
        <Disclaimer />
      </main>
    </div>
  );
}

# backend/market_screener.py
"""
Technical Screener Parameters from the playbook, via yfinance.

yfinance is an unofficial Yahoo Finance scraper — it's free and doesn't
need an API key, but its response shape has changed across versions before
(especially the quarterly financials attributes) and it can be rate
limited. Every check here is wrapped so a failure produces a partial
result with an `error` note instead of crashing the whole scan, and
results are cached briefly (15 min) since price/volume data goes stale
fast but there's no reason to re-fetch on every page load.
"""

from typing import Dict, List, Optional

from . import db

SCREENER_TTL_SECONDS = 900  # 15 minutes

RELATIVE_VOLUME_THRESHOLD = 2.0
QUARTERLY_GROWTH_THRESHOLD_PCT = 25.0


def _empty_result(ticker: str) -> Dict:
    return {
        "ticker": ticker,
        "price": None,
        "relative_volume": None,
        "sma_200": None,
        "above_200sma": None,
        "quarterly_revenue_growth_pct": None,
        "passes_all_filters": False,
        "error": None,
    }


def _quarterly_revenue_growth(tk) -> Optional[float]:
    """
    Year-over-year growth of the latest quarter's revenue vs the same
    quarter a year earlier. (Comparing to the immediately prior quarter
    would mostly measure seasonality — a power producer's mild spring vs
    hot summer swings ~30% every year.) Returns None rather than a
    misleading number if no quarter ~1 year back is available.

    yfinance has used a couple of different attribute names for this across
    versions (quarterly_income_stmt is current, quarterly_financials is the
    older/deprecated one) — try both rather than assuming.
    """
    for attr in ("quarterly_income_stmt", "quarterly_financials"):
        try:
            df = getattr(tk, attr, None)
            if df is None or df.empty:
                continue

            revenue_row = None
            for label in ("Total Revenue", "TotalRevenue", "Revenue"):
                if label in df.index:
                    revenue_row = df.loc[label].dropna().sort_index(ascending=False)
                    break
            if revenue_row is None or len(revenue_row) < 2:
                continue

            latest_date, latest = revenue_row.index[0], float(revenue_row.iloc[0])
            for date, value in revenue_row.iloc[1:].items():
                if 330 <= (latest_date - date).days <= 400:
                    prior = float(value)
                    if prior == 0:
                        break
                    return round((latest - prior) / abs(prior) * 100, 1)
        except Exception:
            continue
    return None


def screen_ticker(ticker: str, force_refresh: bool = False) -> Dict:
    if not force_refresh:
        cached = db.cache_get("market_screen", ticker, ttl_seconds=SCREENER_TTL_SECONDS)
        if cached is not None:
            return cached

    result = _empty_result(ticker)

    try:
        import yfinance as yf
    except ImportError:
        result["error"] = "yfinance is not installed (pip install yfinance)"
        return result

    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1y", interval="1d")

        if hist is None or hist.empty:
            result["error"] = "No price history returned for this ticker"
            db.cache_set("market_screen", ticker, result)
            return result

        last_close = float(hist["Close"].iloc[-1])
        result["price"] = round(last_close, 2)

        if len(hist) >= 200:
            sma_200 = float(hist["Close"].tail(200).mean())
            result["sma_200"] = round(sma_200, 2)
            result["above_200sma"] = last_close > sma_200

        if len(hist) >= 21:
            avg_volume_20d = float(hist["Volume"].iloc[-21:-1].mean())
            today_volume = float(hist["Volume"].iloc[-1])
            if avg_volume_20d > 0:
                result["relative_volume"] = round(today_volume / avg_volume_20d, 2)

        result["quarterly_revenue_growth_pct"] = _quarterly_revenue_growth(tk)

        result["passes_all_filters"] = bool(
            result["relative_volume"] is not None
            and result["relative_volume"] > RELATIVE_VOLUME_THRESHOLD
            and result["above_200sma"]
            and result["quarterly_revenue_growth_pct"] is not None
            and result["quarterly_revenue_growth_pct"] > QUARTERLY_GROWTH_THRESHOLD_PCT
        )

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    db.cache_set("market_screen", ticker, result)
    return result


def screen_many(tickers: List[str], force_refresh: bool = False) -> Dict[str, Dict]:
    return {t: screen_ticker(t, force_refresh=force_refresh) for t in tickers}

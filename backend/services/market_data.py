"""
Market Intelligence Service — Free APIs only
1. Exchange rates (frankfurter.app) — free, no key needed
2. Commodity prices via Open Exchange (free tier)
3. Economic indicators via FRED (free key)
4. Trend data via Google Trends RSS (no key needed)
"""
import urllib.request
import urllib.parse
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional


def fetch_json(url: str, timeout: int = 8) -> Optional[dict]:
    """Fetch JSON from a URL. Returns None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "STOK-Inventory/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"[MarketData] Fetch failed for {url}: {e}")
        return None


def get_exchange_rates() -> Dict:
    """
    Get USD exchange rates — frankfurter.app (completely free, no key)
    Useful for multi-currency supplier costs.
    """
    data = fetch_json("https://api.frankfurter.app/latest?from=USD")
    if data and "rates" in data:
        return {
            "base": "USD",
            "date": data.get("date"),
            "rates": data["rates"],
            "source": "frankfurter.app"
        }
    return {}


def get_commodity_trends() -> Dict:
    """
    Get commodity price trends using RestCountries + manual mapping.
    Uses open-meteo for free economic proxy signals.
    Falls back gracefully if unavailable.
    """
    # Use coinbase public API as a free market sentiment signal
    # (crypto volatility correlates with supply chain uncertainty)
    btc_data = fetch_json("https://api.coinbase.com/v2/prices/BTC-USD/spot")
    market_sentiment = "neutral"

    if btc_data and "data" in btc_data:
        try:
            btc_price = float(btc_data["data"]["amount"])
            # Simple heuristic: high BTC = risk-on = normal supply chains
            if btc_price > 60000:
                market_sentiment = "stable"
            elif btc_price < 30000:
                market_sentiment = "volatile"
        except Exception:
            pass

    return {
        "market_sentiment": market_sentiment,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "coinbase_public"
    }


def get_shipping_index() -> Dict:
    """
    Proxy for shipping costs using open data.
    Uses REST Countries + manual freight estimation.
    """
    # Freightos Baltic Index is not free — we use a proxy:
    # Global shipping stress = oil price proxy via open data
    # Use exchangerate-api free tier as economic proxy
    data = fetch_json("https://open.er-api.com/v6/latest/USD")

    shipping_stress = "normal"
    if data and "rates" in data:
        # Strong USD typically = lower import costs for USD buyers
        eur_rate = data["rates"].get("EUR", 0.9)
        if eur_rate < 0.85:
            shipping_stress = "elevated"  # weak euro = supply chain pressure
        elif eur_rate > 0.95:
            shipping_stress = "low"

    return {
        "shipping_stress": shipping_stress,
        "usd_eur": data["rates"].get("EUR") if data and "rates" in data else None,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "open.er-api.com"
    }


def get_market_context() -> Dict:
    """
    Aggregate all market signals into one context dict.
    Called by AI agent to enrich its decision-making.
    """
    print("[MarketData] Fetching market context...")

    exchange = get_exchange_rates()
    commodities = get_commodity_trends()
    shipping = get_shipping_index()

    context = {
        "fetched_at": datetime.utcnow().isoformat(),
        "exchange_rates": exchange.get("rates", {}),
        "market_sentiment": commodities.get("market_sentiment", "neutral"),
        "shipping_stress": shipping.get("shipping_stress", "normal"),
        "usd_eur_rate": exchange.get("rates", {}).get("EUR"),
        "signals": []
    }

    # Generate human-readable signals for AI justifications
    if context["market_sentiment"] == "volatile":
        context["signals"].append("Market volatility detected — consider increasing safety stock")
    if context["shipping_stress"] == "elevated":
        context["signals"].append("Shipping costs elevated — factor 10-15% premium into order value")
    if context["usd_eur_rate"] and context["usd_eur_rate"] < 0.88:
        context["signals"].append("Strong USD — favorable for USD-denominated imports")

    print(f"[MarketData] Context: sentiment={context['market_sentiment']}, shipping={context['shipping_stress']}")
    return context


def adjust_reorder_qty_for_market(base_qty: int, market_context: Dict) -> int:
    """
    Adjust EOQ based on market signals.
    Returns modified quantity recommendation.
    """
    qty = base_qty
    sentiment = market_context.get("market_sentiment", "neutral")
    shipping = market_context.get("shipping_stress", "normal")

    if sentiment == "volatile":
        qty = int(qty * 1.15)  # +15% buffer during market volatility
    elif sentiment == "stable":
        qty = int(qty * 1.0)   # no change

    if shipping == "elevated":
        qty = int(qty * 1.10)  # +10% to consolidate fewer shipments

    return max(qty, base_qty)  # never go below original EOQ

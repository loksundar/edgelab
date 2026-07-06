"""Realistic Indian intraday equity cost model.

Charges (from config/settings.yaml): flat brokerage per order, STT on the sell
side, exchange transaction charges, SEBI fee, stamp duty on the buy side, GST
on brokerage + transaction charges, plus assumed slippage per side.
"""

from __future__ import annotations

from intraday.config import settings


def round_trip_cost(entry_notional: float, exit_notional: float) -> float:
    """Total cost in rupees for one intraday round trip (buy + sell legs)."""
    c = settings()["costs"]
    buy, sell = (entry_notional, exit_notional)
    brokerage = 2 * c["brokerage_per_order"]
    stt = sell * c["stt_sell_pct"] / 100
    txn = (buy + sell) * c["exchange_txn_pct"] / 100
    sebi = (buy + sell) * c["sebi_fee_pct"] / 100
    stamp = buy * c["stamp_duty_buy_pct"] / 100
    gst = (brokerage + txn) * c["gst_pct"] / 100
    slippage = (buy + sell) * c["slippage_pct"] / 100
    return brokerage + stt + txn + sebi + stamp + gst + slippage


def delivery_round_trip_cost(entry_notional: float, exit_notional: float) -> float:
    """Total cost in rupees for a CNC/delivery round trip (multi-day holds)."""
    c = settings()["costs_delivery"]
    buy, sell = (entry_notional, exit_notional)
    brokerage = 2 * c["brokerage_per_order"]
    stt = (buy + sell) * c["stt_pct"] / 100
    txn = (buy + sell) * c["exchange_txn_pct"] / 100
    sebi = (buy + sell) * c["sebi_fee_pct"] / 100
    stamp = buy * c["stamp_duty_buy_pct"] / 100
    gst = (brokerage + txn) * c["gst_pct"] / 100
    slippage = (buy + sell) * c["slippage_pct"] / 100
    return brokerage + stt + txn + sebi + stamp + gst + slippage + c["dp_charge_sell"]

"""
STOK Agentic AI — Fully Agentic Version
Features:
  1. Prophet ML forecasting
  2. Market data enrichment (free APIs)
  3. Feedback loop — learns from approve/reject history
  4. Email execution on approval
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import Dict
import models
import uuid


def gen_id():
    return str(uuid.uuid4())


def compute_daily_velocity(sales_df: pd.DataFrame, days: int = 30) -> float:
    if sales_df.empty:
        return 0.0
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    recent = sales_df[sales_df["date"] >= cutoff]
    if recent.empty:
        return float(sales_df["quantity_sold"].mean())
    return float(recent["quantity_sold"].sum() / days)


def compute_eoq(annual_demand: float, order_cost: float = 50,
                holding_rate: float = 0.25, unit_cost: float = 10) -> int:
    if annual_demand <= 0 or unit_cost <= 0:
        return 50
    eoq = np.sqrt((2 * annual_demand * order_cost) / (holding_rate * unit_cost))
    return max(1, int(round(eoq)))


# keep old get_forecast name for router compatibility
def get_forecast(sku_id: str, db: Session) -> Dict:
    from services.forecasting import get_forecast_for_sku
    return get_forecast_for_sku(sku_id, db)


def _pick_best_supplier(sku_id: str, db) -> object:
    """Pick the best supplier for a SKU using AI ranking score.

    Scoring: on-time delivery (40%), quality (35%), lead time (15%), cost variance (10%).
    Falls back to preferred supplier, then any linked supplier.
    """
    sku_suppliers = db.query(models.SKUSupplier).filter(
        models.SKUSupplier.sku_id == sku_id
    ).all()

    if not sku_suppliers:
        return None
    if len(sku_suppliers) == 1:
        return sku_suppliers[0]

    best_score = -1
    best_sku_supplier = None

    for sku_sup in sku_suppliers:
        supplier = db.query(models.Supplier).filter(
            models.Supplier.id == sku_sup.supplier_id
        ).first()
        if not supplier:
            continue

        otd = float(supplier.on_time_delivery_rate or 0.8)
        quality = float(supplier.quality_rate or 0.9)
        lead_time = float(supplier.avg_lead_time_days or 14)
        cost_var = float(supplier.cost_variance_pct or 5)

        score = (
            otd * 40 +
            quality * 35 +
            max(0, (30 - lead_time) / 30) * 15 -
            min(cost_var / 10, 1) * 10
        )
        if sku_sup.is_preferred:
            score += 2

        if score > best_score:
            best_score = score
            best_sku_supplier = sku_sup

    return best_sku_supplier or sku_suppliers[0]


def run_agent(db: Session) -> int:
    """
    Fully agentic scan:
    1. Fetch market context from free APIs
    2. Load feedback weights from historical decisions
    3. Forecast demand per SKU using Prophet
    4. Generate actions adjusted for market + feedback
    5. Send email summary if urgent actions found
    """
    actions_created = 0

    # ── Step 1: Market context ────────────────────────────────────
    try:
        from services.market_data import get_market_context, adjust_reorder_qty_for_market
        market_context = get_market_context()
        market_signals = market_context.get("signals", [])
        print(f"[Agent] Market: sentiment={market_context.get('market_sentiment')}, shipping={market_context.get('shipping_stress')}")
    except Exception as e:
        print(f"[Agent] Market data failed: {e}")
        market_context = {}
        market_signals = []

    # ── Step 2: Feedback weights ──────────────────────────────────
    try:
        from services.feedback import compute_feedback_weights, apply_feedback_to_action, log_feedback_run
        weights = compute_feedback_weights(db)
        log_feedback_run(db, weights)
        print(f"[Agent] Feedback: approval_rate={weights['approval_rate']:.2f}, qty_bias={weights['qty_bias']:.2f}, data_points={weights['data_points']}")
    except Exception as e:
        print(f"[Agent] Feedback computation failed: {e}")
        weights = {"approval_rate": 1.0, "qty_bias": 1.0, "confidence_threshold": 70.0,
                   "type_weights": {}, "priority_weights": {}, "data_points": 0}

    # ── Step 3: Scan SKUs ─────────────────────────────────────────
    skus = db.query(models.SKU).filter(models.SKU.is_active == True).all()
    urgent_count = 0

    for sku in skus:
        inv = db.query(models.Inventory).filter(models.Inventory.sku_id == sku.id).first()
        current_stock = inv.quantity if inv else 0

        cutoff = datetime.utcnow() - timedelta(days=60)
        sales = db.query(models.SalesHistory).filter(
            models.SalesHistory.sku_id == sku.id,
            models.SalesHistory.date >= cutoff
        ).all()
        sales_df = pd.DataFrame([{"date": s.date, "quantity_sold": s.quantity_sold} for s in sales])

        velocity = compute_daily_velocity(sales_df)

        # ── Step 4a: Reorder check ────────────────────────────────
        if velocity > 0:
            days_remaining = current_stock / velocity
            days_until_stockout = days_remaining - sku.lead_time_days

            if current_stock <= sku.reorder_point or days_until_stockout <= 5:
                existing = db.query(models.PendingAction).filter(
                    models.PendingAction.sku_id == sku.id,
                    models.PendingAction.type == "order",
                    models.PendingAction.status == "pending"
                ).first()

                if not existing:
                    priority = "urgent" if days_until_stockout <= 1 else \
                               "high" if days_until_stockout <= 3 else "normal"
                    if priority == "urgent":
                        urgent_count += 1

                    annual_demand = velocity * 365
                    base_qty = compute_eoq(annual_demand, unit_cost=sku.unit_cost or 10)
                    base_qty = max(base_qty, sku.moq)

                    # Apply market adjustment
                    try:
                        from services.market_data import adjust_reorder_qty_for_market
                        market_qty = adjust_reorder_qty_for_market(base_qty, market_context)
                    except Exception:
                        market_qty = base_qty

                    # Apply feedback adjustment
                    base_confidence = min(97, max(60,
                        90 - abs(days_until_stockout) * 2 +
                        (10 if current_stock <= sku.safety_stock else 0)
                    ))
                    try:
                        adj_qty, adj_confidence, feedback_note = apply_feedback_to_action(
                            "order", priority, market_qty, base_confidence, weights
                        )
                    except Exception:
                        adj_qty, adj_confidence, feedback_note = market_qty, base_confidence, ""

                    # Find best supplier using AI ranking score
                    sku_supplier = _pick_best_supplier(sku.id, db)

                    supplier_id = sku_supplier.supplier_id if sku_supplier else None
                    unit_cost = (sku_supplier.unit_cost if sku_supplier else None) or sku.unit_cost or 0
                    value = round(adj_qty * unit_cost, 2)

                    # Get supplier name for justification
                    selected_supplier = db.query(models.Supplier).filter(
                        models.Supplier.id == supplier_id
                    ).first() if supplier_id else None
                    supplier_note = f" Selected supplier: {selected_supplier.name} (highest AI ranking score)." if selected_supplier else " No supplier linked — upload sku_suppliers.csv."

                    # Build justification with all intelligence layers
                    market_note = ""
                    if market_signals:
                        market_note = f" Market signals: {'; '.join(market_signals)}."
                    if adj_qty != base_qty:
                        market_note += f" Qty adjusted from EOQ {base_qty} → {adj_qty} (market+feedback)."

                    justification = (
                        f"Current stock: {current_stock} units. "
                        f"Daily velocity: {velocity:.1f} units/day. "
                        f"Days remaining: {days_remaining:.1f}d. "
                        f"Lead time: {sku.lead_time_days}d. "
                        f"Reorder point: {sku.reorder_point}. "
                        f"EOQ: {adj_qty} units.{supplier_note}{market_note}"
                        + (f" Feedback: {feedback_note}." if feedback_note else "")
                    )
                    risks = (
                        f"Stockout in ~{days_remaining:.0f} days. "
                        f"Estimated lost revenue: ${velocity * sku.lead_time_days * (sku.unit_price or 0):.0f}."
                    )

                    db.add(models.PendingAction(
                        id=gen_id(),
                        sku_id=sku.id,
                        type="order",
                        priority=priority,
                        title=f"{'Emergency' if priority=='urgent' else 'Scheduled'} Reorder — {sku.name}",
                        justification=justification,
                        risks=risks,
                        alternatives="Consider expedited shipping if stockout risk is critical.",
                        recommended_qty=adj_qty,
                        recommended_value=value,
                        supplier_id=supplier_id,
                        confidence_score=adj_confidence,
                        extra_data={
                            "base_eoq": base_qty,
                            "market_adjusted_qty": market_qty,
                            "feedback_adjusted_qty": adj_qty,
                            "market_sentiment": market_context.get("market_sentiment"),
                            "shipping_stress": market_context.get("shipping_stress"),
                        }
                    ))
                    actions_created += 1

        # ── Step 4b: Slow mover check ─────────────────────────────
        if velocity < 0.1 and current_stock > 50:
            days_of_supply = current_stock / max(velocity, 0.01)
            if days_of_supply > 180:
                existing = db.query(models.PendingAction).filter(
                    models.PendingAction.sku_id == sku.id,
                    models.PendingAction.type.in_(["price", "return"]),
                    models.PendingAction.status == "pending"
                ).first()
                if not existing:
                    dead_stock_value = current_stock * (sku.unit_cost or 0)

                    base_confidence = 78.0
                    try:
                        _, adj_confidence, feedback_note = apply_feedback_to_action(
                            "price", "normal", 0, base_confidence, weights
                        )
                    except Exception:
                        adj_confidence, feedback_note = base_confidence, ""

                    db.add(models.PendingAction(
                        id=gen_id(),
                        sku_id=sku.id,
                        type="price",
                        priority="normal",
                        title=f"Markdown Recommended — {sku.name}",
                        justification=f"Stock: {current_stock} units. Velocity: {velocity:.2f}/day. {days_of_supply:.0f} days of supply. Recommend 15% markdown to accelerate sell-through." + (f" {feedback_note}" if feedback_note else ""),
                        risks=f"Dead stock value: ${dead_stock_value:.0f}. Risk of obsolescence.",
                        alternatives="Bundle with fast-moving SKU. Return to supplier if contract allows.",
                        recommended_qty=None,
                        recommended_value=-15.0,
                        confidence_score=adj_confidence,
                    ))
                    actions_created += 1

    # ── Step 5: Log + email summary ───────────────────────────────
    db.add(models.AuditLog(
        id=gen_id(),
        user_email="AI Agent",
        event_type="GENERATE",
        detail=f"Agent scan complete — {actions_created} new actions, {urgent_count} urgent, market={market_context.get('market_sentiment','unknown')}",
        outcome="executed",
        meta={
            "skus_scanned": len(skus),
            "actions_created": actions_created,
            "urgent_count": urgent_count,
            "market_context": market_context,
            "feedback_weights": weights,
        }
    ))
    db.commit()

    # Send email summary if any urgent actions
    try:
        from services.email_service import send_agent_summary_email
        send_agent_summary_email(actions_created, len(skus), urgent_count)
    except Exception as e:
        print(f"[Agent] Email summary failed: {e}")

    print(f"[Agent] Done — {actions_created} actions created, {urgent_count} urgent")
    return actions_created

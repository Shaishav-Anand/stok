"""
AI Agent Service
- Runs demand forecasting per SKU
- Detects stockout risks
- Generates pending actions with justifications
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Dict
import models
import uuid
import json


def gen_id():
    return str(uuid.uuid4())


# ── Forecasting ────────────────────────────────────────────────
def compute_daily_velocity(sales_df: pd.DataFrame, days: int = 30) -> float:
    """Average daily sales over the last N days"""
    if sales_df.empty:
        return 0.0
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    recent = sales_df[sales_df["date"] >= cutoff]
    if recent.empty:
        return float(sales_df["quantity_sold"].mean())
    return float(recent["quantity_sold"].sum() / days)


def simple_forecast(sales_df: pd.DataFrame, horizon: int = 30) -> Dict:
    """
    Linear trend + seasonality forecast.
    Falls back to moving average if data is too sparse.
    Returns dict with actual and forecast arrays.
    """
    if len(sales_df) < 7:
        # Not enough data — use flat velocity
        velocity = compute_daily_velocity(sales_df)
        today = datetime.now().date()
        forecast = []
        for i in range(1, horizon + 1):
            d = today + timedelta(days=i)
            noise = np.random.normal(0, velocity * 0.1)
            val = max(0, velocity + noise)
            forecast.append({
                "date": str(d),
                "value": round(val, 1),
                "lower": round(max(0, val * 0.8), 1),
                "upper": round(val * 1.2, 1)
            })
        actual = sales_df.tail(14).apply(
            lambda r: {"date": str(r["date"].date()), "value": int(r["quantity_sold"])}, axis=1
        ).tolist() if not sales_df.empty else []
        return {"actual": actual, "forecast": forecast, "model": "moving_average", "accuracy": None}

    # Sort and prepare
    df = sales_df.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.groupby("date")["quantity_sold"].sum().reset_index()
    df.columns = ["date", "y"]
    df["t"] = (df["date"] - df["date"].min()).dt.days

    # Linear regression
    t = df["t"].values
    y = df["y"].values
    coeffs = np.polyfit(t, y, 1)
    slope, intercept = coeffs

    # Residual std for confidence interval
    y_pred = slope * t + intercept
    residuals = y - y_pred
    std = residuals.std()

    # Actual (last 14 days)
    actual = df.tail(14).apply(
        lambda r: {"date": str(r["date"].date()), "value": int(r["y"])}, axis=1
    ).tolist()

    # Forecast
    last_t = int(df["t"].max())
    today = df["date"].max().date()
    forecast = []
    for i in range(1, horizon + 1):
        ti = last_t + i
        val = max(0, slope * ti + intercept)
        forecast.append({
            "date": str(today + timedelta(days=i)),
            "value": round(val, 1),
            "lower": round(max(0, val - 1.645 * std), 1),
            "upper": round(val + 1.645 * std, 1)
        })

    # Accuracy: 1 - MAPE on last 30% of data
    test_size = max(1, len(df) // 3)
    test = df.tail(test_size)
    pred = slope * test["t"].values + intercept
    mape = np.mean(np.abs((test["y"].values - pred) / np.maximum(test["y"].values, 1))) * 100
    accuracy = round(max(0, 100 - mape), 1)

    return {"actual": actual, "forecast": forecast, "model": "linear_trend", "accuracy": accuracy}


def get_forecast(sku_id: str, db: Session) -> Dict:
    """Get forecast from cache or compute fresh"""
    cache = db.query(models.ForecastCache).filter(
        models.ForecastCache.sku_id == sku_id
    ).first()

    if cache and cache.valid_until and cache.valid_until > datetime.utcnow():
        return {
            "forecast_json": cache.forecast_json,
            "model_used": cache.model_used,
            "accuracy_pct": cache.accuracy_pct,
            "computed_at": cache.computed_at,
        }

    # Fetch sales data
    sales = db.query(models.SalesHistory).filter(
        models.SalesHistory.sku_id == sku_id
    ).all()

    sales_df = pd.DataFrame([{
        "date": pd.to_datetime(s.date),
        "quantity_sold": s.quantity_sold
    } for s in sales])

    result = simple_forecast(sales_df)

    # Cache for 6 hours
    if cache:
        cache.forecast_json = result
        cache.model_used = result["model"]
        cache.accuracy_pct = result.get("accuracy")
        cache.computed_at = datetime.utcnow()
        cache.valid_until = datetime.utcnow() + timedelta(hours=6)
    else:
        db.add(models.ForecastCache(
            id=gen_id(),
            sku_id=sku_id,
            forecast_json=result,
            model_used=result["model"],
            accuracy_pct=result.get("accuracy"),
            valid_until=datetime.utcnow() + timedelta(hours=6),
        ))

    db.commit()
    return {"forecast_json": result, "model_used": result["model"],
            "accuracy_pct": result.get("accuracy"), "computed_at": datetime.utcnow()}


# ── AI Agent ───────────────────────────────────────────────────
def compute_eoq(annual_demand: float, order_cost: float = 50, holding_rate: float = 0.25, unit_cost: float = 10) -> int:
    """Economic Order Quantity formula"""
    if annual_demand <= 0 or unit_cost <= 0:
        return 50
    eoq = np.sqrt((2 * annual_demand * order_cost) / (holding_rate * unit_cost))
    return max(1, int(round(eoq)))


def run_agent(db: Session) -> int:
    """
    Main AI agent loop. Scans all SKUs and creates pending actions.
    Returns number of actions created.
    """
    actions_created = 0
    skus = db.query(models.SKU).filter(models.SKU.is_active == True).all()

    for sku in skus:
        inv = db.query(models.Inventory).filter(models.Inventory.sku_id == sku.id).first()
        current_stock = inv.quantity if inv else 0

        # Get recent sales for velocity
        cutoff = datetime.utcnow() - timedelta(days=30)
        sales = db.query(models.SalesHistory).filter(
            models.SalesHistory.sku_id == sku.id,
            models.SalesHistory.date >= cutoff
        ).all()
        sales_df = pd.DataFrame([{"date": s.date, "quantity_sold": s.quantity_sold} for s in sales])

        velocity = compute_daily_velocity(sales_df)

        # ── Check: Reorder needed? ────────────────────────────
        if velocity > 0:
            days_remaining = current_stock / velocity
            days_until_stockout = days_remaining - sku.lead_time_days

            if current_stock <= sku.reorder_point or days_until_stockout <= 3:
                # Check no pending order already exists
                existing = db.query(models.PendingAction).filter(
                    models.PendingAction.sku_id == sku.id,
                    models.PendingAction.type == "order",
                    models.PendingAction.status == "pending"
                ).first()

                if not existing:
                    priority = "urgent" if days_until_stockout <= 1 else "high" if days_until_stockout <= 3 else "normal"
                    annual_demand = velocity * 365
                    qty = compute_eoq(annual_demand, unit_cost=sku.unit_cost or 10)
                    qty = max(qty, sku.moq)

                    # Find best supplier
                    sku_supplier = db.query(models.SKUSupplier).filter(
                        models.SKUSupplier.sku_id == sku.id,
                        models.SKUSupplier.is_preferred == True
                    ).first()
                    if not sku_supplier:
                        sku_supplier = db.query(models.SKUSupplier).filter(
                            models.SKUSupplier.sku_id == sku.id
                        ).first()

                    supplier_id = sku_supplier.supplier_id if sku_supplier else None
                    supplier = db.query(models.Supplier).filter(models.Supplier.id == supplier_id).first() if supplier_id else None
                    unit_cost = sku_supplier.unit_cost if sku_supplier else sku.unit_cost or 0
                    value = round(qty * unit_cost, 2)

                    justification = (
                        f"Current stock: {current_stock} units. "
                        f"Daily velocity: {velocity:.1f} units/day. "
                        f"Days remaining: {days_remaining:.1f}d. "
                        f"Lead time: {sku.lead_time_days}d. "
                        f"Reorder point: {sku.reorder_point}. "
                        f"EOQ calculation suggests {qty} units."
                    )
                    risks = (
                        f"Stockout in ~{days_remaining:.0f} days. "
                        f"Estimated lost revenue: ${velocity * sku.lead_time_days * (sku.unit_price or 0):.0f}."
                    )

                    confidence = min(97, max(60, 90 - abs(days_until_stockout) * 2 + (10 if current_stock <= sku.safety_stock else 0)))

                    action = models.PendingAction(
                        id=gen_id(),
                        sku_id=sku.id,
                        type="order",
                        priority=priority,
                        title=f"{'Emergency' if priority=='urgent' else 'Scheduled'} Reorder — {sku.name}",
                        justification=justification,
                        risks=risks,
                        alternatives="Consider expedited shipping if stockout risk is critical.",
                        recommended_qty=qty,
                        recommended_value=value,
                        supplier_id=supplier_id,
                        confidence_score=confidence,
                    )
                    db.add(action)
                    actions_created += 1

        # ── Check: Slow mover? ────────────────────────────────
        if velocity < 0.1 and current_stock > 50:
            days_of_supply = current_stock / max(velocity, 0.01)
            if days_of_supply > 180:
                existing = db.query(models.PendingAction).filter(
                    models.PendingAction.sku_id == sku.id,
                    models.PendingAction.type.in_(["price", "return"]),
                    models.PendingAction.status == "pending"
                ).first()
                if not existing:
                    value = current_stock * (sku.unit_cost or 0)
                    action = models.PendingAction(
                        id=gen_id(),
                        sku_id=sku.id,
                        type="price",
                        priority="normal",
                        title=f"Markdown Recommended — {sku.name}",
                        justification=f"Stock: {current_stock} units. Velocity: {velocity:.2f}/day. {days_of_supply:.0f} days of supply. Recommend 15-20% markdown to accelerate sell-through.",
                        risks=f"Dead stock value: ${value:.0f}. Risk of obsolescence.",
                        alternatives="Bundle with fast-moving SKU. Return to supplier if contract allows.",
                        recommended_qty=None,
                        recommended_value=-15.0,  # percentage
                        confidence_score=78,
                    )
                    db.add(action)
                    actions_created += 1

    # Log the agent run
    db.add(models.AuditLog(
        id=gen_id(),
        user_email="AI Agent",
        event_type="GENERATE",
        detail=f"Agent scan complete — {actions_created} new actions created",
        outcome="executed",
        meta={"skus_scanned": len(skus), "actions_created": actions_created}
    ))
    db.commit()
    return actions_created

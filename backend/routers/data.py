from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import get_db
from services.auth import get_current_user
from services.agent import compute_daily_velocity, get_forecast, run_agent
import models, schemas
import pandas as pd

# ── Inventory ──────────────────────────────────────────────────
inventory_router = APIRouter(prefix="/inventory", tags=["inventory"])

@inventory_router.get("/", response_model=list[schemas.SKUOut])
def get_inventory(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    skus = db.query(models.SKU).filter(models.SKU.is_active == True).all()
    result = []

    for sku in skus:
        inv = db.query(models.Inventory).filter(models.Inventory.sku_id == sku.id).first()
        current_stock = inv.quantity if inv else 0

        # Get 30-day velocity
        cutoff = datetime.utcnow() - timedelta(days=30)
        sales = db.query(models.SalesHistory).filter(
            models.SalesHistory.sku_id == sku.id,
            models.SalesHistory.date >= cutoff
        ).all()
        sales_df = pd.DataFrame([{"date": s.date, "quantity_sold": s.quantity_sold} for s in sales])
        velocity = compute_daily_velocity(sales_df)

        days_remaining = (current_stock / velocity) if velocity > 0 else None

        # Risk level
        if days_remaining is not None:
            if days_remaining <= sku.lead_time_days:
                risk = "critical"
            elif days_remaining <= sku.lead_time_days * 2:
                risk = "high"
            elif current_stock > sku.reorder_point * 5 and velocity < 0.2:
                risk = "medium"  # slow mover
            else:
                risk = "low"
        else:
            risk = "low"

        # Trend (last 8 days)
        trend_sales = db.query(models.SalesHistory).filter(
            models.SalesHistory.sku_id == sku.id,
            models.SalesHistory.date >= datetime.utcnow() - timedelta(days=8)
        ).order_by(models.SalesHistory.date).all()
        trend = [s.quantity_sold for s in trend_sales]

        result.append(schemas.SKUOut(
            id=sku.id,
            sku_code=sku.sku_code,
            name=sku.name,
            category=sku.category,
            unit_cost=sku.unit_cost,
            unit_price=sku.unit_price,
            reorder_point=sku.reorder_point,
            safety_stock=sku.safety_stock,
            lead_time_days=sku.lead_time_days,
            current_stock=current_stock,
            daily_velocity=round(velocity, 2),
            days_remaining=round(days_remaining, 1) if days_remaining else None,
            risk_level=risk,
            trend=trend
        ))

    return result


# ── Suppliers ──────────────────────────────────────────────────
suppliers_router = APIRouter(prefix="/suppliers", tags=["suppliers"])

@suppliers_router.get("/", response_model=list[schemas.SupplierOut])
def get_suppliers(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Supplier).filter(
        models.Supplier.is_active == True
    ).order_by(models.Supplier.ai_rank).all()


# ── Audit ──────────────────────────────────────────────────────
audit_router = APIRouter(prefix="/audit", tags=["audit"])

@audit_router.get("/", response_model=list[schemas.AuditOut])
def get_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.AuditLog).order_by(
        models.AuditLog.timestamp.desc()
    ).limit(limit).all()


# ── Forecast ───────────────────────────────────────────────────
forecast_router = APIRouter(prefix="/forecast", tags=["forecast"])

@forecast_router.get("/{sku_code}", response_model=schemas.ForecastOut)
def get_sku_forecast(
    sku_code: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    sku = db.query(models.SKU).filter(models.SKU.sku_code == sku_code).first()
    if not sku:
        from fastapi import HTTPException
        raise HTTPException(404, f"SKU {sku_code} not found")

    result = get_forecast(sku.id, db)
    fc = result["forecast_json"]

    return schemas.ForecastOut(
        sku_code=sku.sku_code,
        sku_name=sku.name,
        actual=fc.get("actual", []),
        forecast=fc.get("forecast", []),
        model_used=result["model_used"],
        accuracy_pct=result["accuracy_pct"],
        computed_at=result["computed_at"]
    )


# ── Dashboard Stats ────────────────────────────────────────────
stats_router = APIRouter(prefix="/stats", tags=["stats"])

@stats_router.get("/dashboard", response_model=schemas.DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    total_skus = db.query(models.SKU).filter(models.SKU.is_active == True).count()
    pending_actions = db.query(models.PendingAction).filter(models.PendingAction.status == "pending").all()
    pending_value = sum(a.recommended_value or 0 for a in pending_actions if a.type == "order")

    # Count risk levels by scanning inventory
    critical = high = slow_movers = slow_value = 0
    skus = db.query(models.SKU).filter(models.SKU.is_active == True).all()

    for sku in skus:
        inv = db.query(models.Inventory).filter(models.Inventory.sku_id == sku.id).first()
        stock = inv.quantity if inv else 0
        cutoff = datetime.utcnow() - timedelta(days=30)
        sales = db.query(models.SalesHistory).filter(
            models.SalesHistory.sku_id == sku.id,
            models.SalesHistory.date >= cutoff
        ).all()
        sales_df = pd.DataFrame([{"date": s.date, "quantity_sold": s.quantity_sold} for s in sales])
        v = compute_daily_velocity(sales_df)
        if v > 0:
            days = stock / v
            if days <= sku.lead_time_days: critical += 1
            elif days <= sku.lead_time_days * 2: high += 1
        if v < 0.1 and stock > 50:
            slow_movers += 1
            slow_value += stock * (sku.unit_cost or 0)

    # AI accuracy from forecast caches
    caches = db.query(models.ForecastCache).filter(models.ForecastCache.accuracy_pct.isnot(None)).all()
    ai_accuracy = round(sum(c.accuracy_pct for c in caches) / len(caches), 1) if caches else None

    return schemas.DashboardStats(
        total_skus=total_skus,
        stockout_risk_count=critical + high,
        critical_count=critical,
        pending_actions_count=len(pending_actions),
        pending_value=round(pending_value, 2),
        ai_accuracy=ai_accuracy,
        slow_movers_count=slow_movers,
        slow_movers_value=round(slow_value, 2)
    )


# ── Agent Trigger ──────────────────────────────────────────────
agent_router = APIRouter(prefix="/agent", tags=["agent"])

@agent_router.post("/run")
def trigger_agent(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Manually trigger the AI agent scan"""
    count = run_agent(db)
    return {"message": f"Agent completed. {count} new actions generated."}

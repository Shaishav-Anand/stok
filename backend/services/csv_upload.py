"""
CSV Upload Service
Handles 3 types of CSV uploads:
  1. skus.csv         — product master data
  2. sales.csv        — historical sales
  3. inventory.csv    — current stock levels
  4. suppliers.csv    — supplier info
"""
import pandas as pd
import numpy as np
from io import StringIO
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Tuple
import models
import uuid


def gen_id():
    return str(uuid.uuid4())


# ── Expected CSV columns ──────────────────────────────────────
SCHEMAS = {
    "skus": {
        "required": ["sku_code", "name"],
        "optional": ["category", "unit_cost", "unit_price", "reorder_point",
                     "safety_stock", "lead_time_days", "moq"]
    },
    "sales": {
        "required": ["sku_code", "date", "quantity_sold"],
        "optional": ["revenue", "channel"]
    },
    "inventory": {
        "required": ["sku_code", "quantity"],
        "optional": ["location"]
    },
    "suppliers": {
        "required": ["code", "name"],
        "optional": ["contact_email", "avg_lead_time_days", "on_time_delivery_rate",
                     "quality_rate", "cost_variance_pct"]
    }
}


def parse_csv(content: bytes) -> pd.DataFrame:
    text = content.decode("utf-8-sig")  # handles BOM from Excel
    return pd.read_csv(StringIO(text))


def validate_columns(df: pd.DataFrame, file_type: str) -> list[str]:
    """Returns list of missing required columns"""
    required = SCHEMAS[file_type]["required"]
    missing = [c for c in required if c not in df.columns]
    return missing


def upload_skus(df: pd.DataFrame, db: Session) -> Tuple[int, int, list]:
    inserted = 0
    failed = 0
    errors = []

    for i, row in df.iterrows():
        try:
            existing = db.query(models.SKU).filter(
                models.SKU.sku_code == str(row["sku_code"]).strip()
            ).first()

            if existing:
                # Update existing
                existing.name = str(row["name"]).strip()
                existing.category = str(row.get("category", existing.category or "")).strip() or None
                if "unit_cost" in row and pd.notna(row["unit_cost"]):
                    existing.unit_cost = float(row["unit_cost"])
                if "unit_price" in row and pd.notna(row["unit_price"]):
                    existing.unit_price = float(row["unit_price"])
                if "reorder_point" in row and pd.notna(row["reorder_point"]):
                    existing.reorder_point = int(row["reorder_point"])
                if "safety_stock" in row and pd.notna(row["safety_stock"]):
                    existing.safety_stock = int(row["safety_stock"])
                if "lead_time_days" in row and pd.notna(row["lead_time_days"]):
                    existing.lead_time_days = int(row["lead_time_days"])
                if "moq" in row and pd.notna(row["moq"]):
                    existing.moq = int(row["moq"])
            else:
                # Create new
                sku = models.SKU(
                    id=gen_id(),
                    sku_code=str(row["sku_code"]).strip(),
                    name=str(row["name"]).strip(),
                    category=str(row.get("category", "")).strip() or None,
                    unit_cost=float(row["unit_cost"]) if "unit_cost" in row and pd.notna(row.get("unit_cost")) else None,
                    unit_price=float(row["unit_price"]) if "unit_price" in row and pd.notna(row.get("unit_price")) else None,
                    reorder_point=int(row["reorder_point"]) if "reorder_point" in row and pd.notna(row.get("reorder_point")) else 20,
                    safety_stock=int(row["safety_stock"]) if "safety_stock" in row and pd.notna(row.get("safety_stock")) else 10,
                    lead_time_days=int(row["lead_time_days"]) if "lead_time_days" in row and pd.notna(row.get("lead_time_days")) else 7,
                    moq=int(row["moq"]) if "moq" in row and pd.notna(row.get("moq")) else 1,
                )
                db.add(sku)
                # Create empty inventory record
                db.flush()
                inv = db.query(models.Inventory).filter(models.Inventory.sku_id == sku.id).first()
                if not inv:
                    db.add(models.Inventory(id=gen_id(), sku_id=sku.id, quantity=0))

            inserted += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i+2}: {str(e)}")

    db.commit()
    return inserted, failed, errors


def upload_sales(df: pd.DataFrame, db: Session) -> Tuple[int, int, list]:
    inserted = 0
    failed = 0
    errors = []

    # Build SKU code → id map
    skus = {s.sku_code: s.id for s in db.query(models.SKU).all()}

    for i, row in df.iterrows():
        try:
            sku_code = str(row["sku_code"]).strip()
            if sku_code not in skus:
                errors.append(f"Row {i+2}: SKU '{sku_code}' not found — upload skus.csv first")
                failed += 1
                continue

            # Parse date flexibly
            sale_date = pd.to_datetime(row["date"])

            # Check for duplicate
            existing = db.query(models.SalesHistory).filter(
                models.SalesHistory.sku_id == skus[sku_code],
                models.SalesHistory.date == sale_date,
                models.SalesHistory.channel == str(row.get("channel", "online"))
            ).first()

            if existing:
                existing.quantity_sold = int(row["quantity_sold"])
                if "revenue" in row and pd.notna(row.get("revenue")):
                    existing.revenue = float(row["revenue"])
            else:
                db.add(models.SalesHistory(
                    id=gen_id(),
                    sku_id=skus[sku_code],
                    date=sale_date,
                    quantity_sold=int(row["quantity_sold"]),
                    revenue=float(row["revenue"]) if "revenue" in row and pd.notna(row.get("revenue")) else None,
                    channel=str(row.get("channel", "online")).strip(),
                ))

            inserted += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i+2}: {str(e)}")

    db.commit()
    return inserted, failed, errors


def upload_inventory(df: pd.DataFrame, db: Session) -> Tuple[int, int, list]:
    inserted = 0
    failed = 0
    errors = []

    skus = {s.sku_code: s.id for s in db.query(models.SKU).all()}

    for i, row in df.iterrows():
        try:
            sku_code = str(row["sku_code"]).strip()
            if sku_code not in skus:
                errors.append(f"Row {i+2}: SKU '{sku_code}' not found")
                failed += 1
                continue

            inv = db.query(models.Inventory).filter(
                models.Inventory.sku_id == skus[sku_code]
            ).first()

            if inv:
                inv.quantity = int(row["quantity"])
                inv.location = str(row.get("location", "Warehouse A")).strip()
            else:
                db.add(models.Inventory(
                    id=gen_id(),
                    sku_id=skus[sku_code],
                    quantity=int(row["quantity"]),
                    location=str(row.get("location", "Warehouse A")).strip(),
                ))

            inserted += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i+2}: {str(e)}")

    db.commit()
    return inserted, failed, errors


def upload_suppliers(df: pd.DataFrame, db: Session) -> Tuple[int, int, list]:
    inserted = 0
    failed = 0
    errors = []

    for i, row in df.iterrows():
        try:
            existing = db.query(models.Supplier).filter(
                models.Supplier.code == str(row["code"]).strip()
            ).first()

            if existing:
                existing.name = str(row["name"]).strip()
                if "contact_email" in row and pd.notna(row.get("contact_email")):
                    existing.contact_email = str(row["contact_email"]).strip()
                if "avg_lead_time_days" in row and pd.notna(row.get("avg_lead_time_days")):
                    existing.avg_lead_time_days = float(row["avg_lead_time_days"])
                if "on_time_delivery_rate" in row and pd.notna(row.get("on_time_delivery_rate")):
                    existing.on_time_delivery_rate = float(row["on_time_delivery_rate"])
                if "quality_rate" in row and pd.notna(row.get("quality_rate")):
                    existing.quality_rate = float(row["quality_rate"])
                if "cost_variance_pct" in row and pd.notna(row.get("cost_variance_pct")):
                    existing.cost_variance_pct = float(row["cost_variance_pct"])
            else:
                db.add(models.Supplier(
                    id=gen_id(),
                    code=str(row["code"]).strip(),
                    name=str(row["name"]).strip(),
                    contact_email=str(row.get("contact_email", "")).strip() or None,
                    avg_lead_time_days=float(row["avg_lead_time_days"]) if "avg_lead_time_days" in row and pd.notna(row.get("avg_lead_time_days")) else None,
                    on_time_delivery_rate=float(row["on_time_delivery_rate"]) if "on_time_delivery_rate" in row and pd.notna(row.get("on_time_delivery_rate")) else None,
                    quality_rate=float(row["quality_rate"]) if "quality_rate" in row and pd.notna(row.get("quality_rate")) else None,
                    cost_variance_pct=float(row["cost_variance_pct"]) if "cost_variance_pct" in row and pd.notna(row.get("cost_variance_pct")) else None,
                ))

            inserted += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i+2}: {str(e)}")

    # Re-rank suppliers by composite score
    _rank_suppliers(db)
    db.commit()
    return inserted, failed, errors


def _rank_suppliers(db: Session):
    """Compute AI ranking score for each supplier"""
    suppliers = db.query(models.Supplier).filter(models.Supplier.is_active == True).all()
    scored = []
    for s in suppliers:
        score = 0
        if s.on_time_delivery_rate: score += s.on_time_delivery_rate * 0.4
        if s.quality_rate: score += s.quality_rate * 0.35
        if s.avg_lead_time_days: score -= s.avg_lead_time_days * 0.5
        if s.cost_variance_pct: score -= s.cost_variance_pct * 0.25
        scored.append((s, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    for rank, (supplier, _) in enumerate(scored, 1):
        supplier.ai_rank = rank

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from services.auth import get_current_user
from services import csv_upload
import pandas as pd
import schemas, models
import uuid

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/skus", response_model=schemas.UploadResult)
async def upload_skus(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")

    content = await file.read()
    df = csv_upload.parse_csv(content)
    missing = csv_upload.validate_columns(df, "skus")
    if missing:
        raise HTTPException(400, f"Missing required columns: {missing}")

    inserted, failed, errors = csv_upload.upload_skus(df, db)

    _log(db, current_user, "UPLOAD", "sku", f"SKUs CSV: {inserted} inserted, {failed} failed")
    return schemas.UploadResult(
        rows_processed=len(df),
        rows_inserted=inserted,
        rows_failed=failed,
        errors=errors[:20],  # cap error list
        message=f"Processed {len(df)} rows. {inserted} inserted/updated, {failed} failed."
    )


@router.post("/sales", response_model=schemas.UploadResult)
async def upload_sales(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")

    content = await file.read()
    df = csv_upload.parse_csv(content)
    missing = csv_upload.validate_columns(df, "sales")
    if missing:
        raise HTTPException(400, f"Missing required columns: {missing}")

    inserted, failed, errors = csv_upload.upload_sales(df, db)

    # Invalidate forecast caches after new sales data
    db.query(models.ForecastCache).delete()
    db.commit()

    _log(db, current_user, "UPLOAD", "sales", f"Sales CSV: {inserted} inserted, {failed} failed")
    return schemas.UploadResult(
        rows_processed=len(df),
        rows_inserted=inserted,
        rows_failed=failed,
        errors=errors[:20],
        message=f"Processed {len(df)} rows. Forecast caches cleared."
    )


@router.post("/inventory", response_model=schemas.UploadResult)
async def upload_inventory(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")

    content = await file.read()
    df = csv_upload.parse_csv(content)
    missing = csv_upload.validate_columns(df, "inventory")
    if missing:
        raise HTTPException(400, f"Missing required columns: {missing}")

    inserted, failed, errors = csv_upload.upload_inventory(df, db)
    _log(db, current_user, "UPLOAD", "inventory", f"Inventory CSV: {inserted} rows updated")
    return schemas.UploadResult(
        rows_processed=len(df),
        rows_inserted=inserted,
        rows_failed=failed,
        errors=errors[:20],
        message=f"Updated {inserted} inventory records."
    )


@router.post("/suppliers", response_model=schemas.UploadResult)
async def upload_suppliers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")

    content = await file.read()
    df = csv_upload.parse_csv(content)
    missing = csv_upload.validate_columns(df, "suppliers")
    if missing:
        raise HTTPException(400, f"Missing required columns: {missing}")

    inserted, failed, errors = csv_upload.upload_suppliers(df, db)
    _log(db, current_user, "UPLOAD", "supplier", f"Suppliers CSV: {inserted} inserted/updated")
    return schemas.UploadResult(
        rows_processed=len(df),
        rows_inserted=inserted,
        rows_failed=failed,
        errors=errors[:20],
        message=f"Updated {inserted} suppliers. AI ranking recalculated."
    )


def _log(db, user, event_type, entity_type, detail):
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        user_email=user.email,
        event_type=event_type,
        entity_type=entity_type,
        detail=detail,
        outcome="executed"
    ))
    db.commit()


@router.post("/sku-suppliers", response_model=schemas.UploadResult)
async def upload_sku_suppliers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")

    content = await file.read()
    df = csv_upload.parse_csv(content)

    required = ["sku_code", "supplier_code"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(400, f"Missing required columns: {missing}")

    inserted = 0
    failed = 0
    errors = []

    # Build lookup maps
    skus = {s.sku_code: s.id for s in db.query(models.SKU).all()}
    suppliers = {s.code: s.id for s in db.query(models.Supplier).all()}

    for i, row in df.iterrows():
        try:
            sku_code = str(row["sku_code"]).strip()
            supplier_code = str(row["supplier_code"]).strip()

            if sku_code not in skus:
                errors.append(f"Row {i+2}: SKU '{sku_code}' not found")
                failed += 1
                continue
            if supplier_code not in suppliers:
                errors.append(f"Row {i+2}: Supplier '{supplier_code}' not found")
                failed += 1
                continue

            sku_id = skus[sku_code]
            supplier_id = suppliers[supplier_code]
            is_preferred = str(row.get("is_preferred", "false")).lower() in ("true", "1", "yes")

            existing = db.query(models.SKUSupplier).filter(
                models.SKUSupplier.sku_id == sku_id,
                models.SKUSupplier.supplier_id == supplier_id
            ).first()

            if existing:
                if "unit_cost" in row and pd.notna(row.get("unit_cost")):
                    existing.unit_cost = float(row["unit_cost"])
                if "lead_time_days" in row and pd.notna(row.get("lead_time_days")):
                    existing.lead_time_days = int(row["lead_time_days"])
                if "moq" in row and pd.notna(row.get("moq")):
                    existing.moq = int(row["moq"])
                existing.is_preferred = is_preferred
            else:
                db.add(models.SKUSupplier(
                    id=str(uuid.uuid4()),
                    sku_id=sku_id,
                    supplier_id=supplier_id,
                    unit_cost=float(row["unit_cost"]) if "unit_cost" in row and pd.notna(row.get("unit_cost")) else None,
                    lead_time_days=int(row["lead_time_days"]) if "lead_time_days" in row and pd.notna(row.get("lead_time_days")) else None,
                    moq=int(row["moq"]) if "moq" in row and pd.notna(row.get("moq")) else 1,
                    is_preferred=is_preferred,
                ))
            inserted += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i+2}: {str(e)}")

    db.commit()
    _log(db, current_user, "UPLOAD", "sku_supplier", f"SKU-Supplier links: {inserted} inserted/updated, {failed} failed")
    return schemas.UploadResult(
        rows_processed=len(df),
        rows_inserted=inserted,
        rows_failed=failed,
        errors=errors[:20],
        message=f"Linked {inserted} SKU-supplier pairs. Supplier names will now appear in orders."
    )

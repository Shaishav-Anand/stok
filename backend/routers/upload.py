from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from services.auth import get_current_user
from services import csv_upload
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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import get_db
from services.auth import get_current_user
import models, schemas
import uuid

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("/", response_model=list[schemas.ActionOut])
def get_actions(
    status: str = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    q = db.query(models.PendingAction)
    if status:
        q = q.filter(models.PendingAction.status == status)
    actions = q.order_by(models.PendingAction.created_at.desc()).all()

    result = []
    for a in actions:
        supplier = db.query(models.Supplier).filter(models.Supplier.id == a.supplier_id).first() if a.supplier_id else None
        result.append(schemas.ActionOut(
            id=a.id,
            sku_id=a.sku_id,
            sku_code=a.sku.sku_code if a.sku else None,
            sku_name=a.sku.name if a.sku else None,
            type=a.type,
            priority=a.priority,
            title=a.title,
            justification=a.justification,
            risks=a.risks,
            alternatives=a.alternatives,
            recommended_qty=a.recommended_qty,
            recommended_value=a.recommended_value,
            supplier_name=supplier.name if supplier else None,
            confidence_score=a.confidence_score,
            status=a.status,
            created_at=a.created_at,
        ))
    return result


@router.post("/{action_id}/approve")
def approve_action(
    action_id: str,
    data: schemas.ActionApprove,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    action = db.query(models.PendingAction).filter(models.PendingAction.id == action_id).first()
    if not action:
        raise HTTPException(404, "Action not found")
    if action.status != "pending":
        raise HTTPException(400, f"Action is already {action.status}")

    modified = data.quantity_override is not None and data.quantity_override != action.recommended_qty
    if modified:
        action.recommended_qty = data.quantity_override

    action.status = "approved"
    action.reviewed_at = datetime.utcnow()
    action.reviewed_by = current_user.id

    outcome = "modified" if modified else "approved"
    detail = f"{action.sku.sku_code if action.sku else ''} {action.type}"
    if modified:
        detail += f" — qty modified to {data.quantity_override}"
    if data.notes:
        detail += f" | Note: {data.notes}"

    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        user_email=current_user.email,
        event_type="APPROVE",
        entity_type="action",
        entity_id=action_id,
        detail=detail,
        outcome=outcome,
        meta={"qty_override": data.quantity_override, "notes": data.notes}
    ))
    db.commit()

    # In a real system: trigger external API call here (supplier PO, price update, etc.)
    # For now, mark as executed immediately after approval
    _execute_action(action, db, current_user)

    return {"message": "Action approved", "outcome": outcome}


@router.post("/{action_id}/reject")
def reject_action(
    action_id: str,
    data: schemas.ActionReject,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    action = db.query(models.PendingAction).filter(models.PendingAction.id == action_id).first()
    if not action:
        raise HTTPException(404, "Action not found")
    if action.status != "pending":
        raise HTTPException(400, f"Action is already {action.status}")

    action.status = "rejected"
    action.reviewed_at = datetime.utcnow()
    action.reviewed_by = current_user.id

    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        user_email=current_user.email,
        event_type="REJECT",
        entity_type="action",
        entity_id=action_id,
        detail=f"{action.sku.sku_code if action.sku else ''} {action.type} — {data.reason or 'No reason given'}",
        outcome="rejected",
        meta={"reason": data.reason}
    ))
    db.commit()
    return {"message": "Action rejected"}


def _execute_action(action: models.PendingAction, db: Session, user: models.User):
    """
    Placeholder for real execution.
    Currently just logs the execution.
    In production: call supplier API, update ERP, send PO email, etc.
    """
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        user_email="AI Agent",
        event_type="EXECUTE",
        entity_type="action",
        entity_id=action.id,
        detail=f"Executed {action.type} for {action.sku.sku_code if action.sku else ''} — qty {action.recommended_qty}",
        outcome="executed"
    ))
    db.commit()

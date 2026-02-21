"""
Feedback Loop Service
Learns from manager approve/reject decisions to improve future recommendations.

How it works:
- Tracks approval rate per action type, SKU category, priority level
- Adjusts confidence thresholds based on historical accuracy
- Learns quantity bias (managers often order more/less than AI suggests)
- Stores learned weights in DB and applies them in future agent runs
"""
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Dict, Tuple
import models
import uuid


def gen_id():
    return str(uuid.uuid4())


def compute_feedback_weights(db: Session) -> Dict:
    """
    Analyze historical approve/reject patterns.
    Returns a weights dict the agent uses to calibrate recommendations.
    """
    # Get all reviewed actions from last 90 days
    cutoff = datetime.utcnow() - timedelta(days=90)
    reviewed = db.query(models.PendingAction).filter(
        models.PendingAction.status.in_(["approved", "rejected"]),
        models.PendingAction.reviewed_at >= cutoff
    ).all()

    if len(reviewed) < 3:
        # Not enough data yet — use defaults
        return {
            "approval_rate": 1.0,
            "qty_bias": 1.0,
            "confidence_threshold": 70.0,
            "type_weights": {},
            "priority_weights": {},
            "data_points": len(reviewed),
            "computed_at": datetime.utcnow().isoformat()
        }

    total = len(reviewed)
    approved = [a for a in reviewed if a.status == "approved"]
    rejected = [a for a in reviewed if a.status == "rejected"]

    approval_rate = len(approved) / total if total > 0 else 1.0

    # ── Quantity bias ─────────────────────────────────────────────
    # If manager consistently orders more/less than AI recommends
    qty_ratios = []
    for action in approved:
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.entity_id == action.id,
            models.AuditLog.outcome == "modified"
        ).first()
        if audit and audit.meta and audit.meta.get("qty_override") and action.recommended_qty:
            ratio = audit.meta["qty_override"] / action.recommended_qty
            qty_ratios.append(ratio)

    qty_bias = float(np.mean(qty_ratios)) if qty_ratios else 1.0
    qty_bias = max(0.5, min(2.0, qty_bias))  # cap between 0.5x and 2x

    # ── Approval rate by action type ──────────────────────────────
    type_weights = {}
    for action_type in ["order", "transfer", "price", "return", "disposal"]:
        type_actions = [a for a in reviewed if a.type == action_type]
        if type_actions:
            type_approved = sum(1 for a in type_actions if a.status == "approved")
            type_weights[action_type] = type_approved / len(type_actions)

    # ── Approval rate by priority ─────────────────────────────────
    priority_weights = {}
    for priority in ["urgent", "high", "normal"]:
        p_actions = [a for a in reviewed if a.priority == priority]
        if p_actions:
            p_approved = sum(1 for a in p_actions if a.status == "approved")
            priority_weights[priority] = p_approved / len(p_actions)

    # ── Confidence threshold ──────────────────────────────────────
    # Find minimum confidence score of approved actions
    approved_confidences = [a.confidence_score for a in approved if a.confidence_score]
    confidence_threshold = float(np.percentile(approved_confidences, 25)) if approved_confidences else 70.0

    weights = {
        "approval_rate": round(approval_rate, 3),
        "qty_bias": round(qty_bias, 3),
        "confidence_threshold": round(confidence_threshold, 1),
        "type_weights": type_weights,
        "priority_weights": priority_weights,
        "data_points": total,
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "computed_at": datetime.utcnow().isoformat()
    }

    return weights


def apply_feedback_to_action(
    action_type: str,
    priority: str,
    base_qty: int,
    base_confidence: float,
    weights: Dict
) -> Tuple[int, float, str]:
    """
    Apply learned weights to adjust a new action recommendation.
    Returns (adjusted_qty, adjusted_confidence, feedback_note)
    """
    notes = []

    # Adjust quantity by learned bias
    qty_bias = weights.get("qty_bias", 1.0)
    adjusted_qty = int(round(base_qty * qty_bias))
    if abs(qty_bias - 1.0) > 0.05:
        direction = "more" if qty_bias > 1.0 else "less"
        notes.append(f"Qty adjusted {direction} ({qty_bias:.2f}x) based on {weights.get('data_points',0)} historical decisions")

    # Adjust confidence based on type approval rate
    type_rate = weights.get("type_weights", {}).get(action_type)
    adjusted_confidence = base_confidence
    if type_rate is not None:
        # Scale confidence by historical approval rate for this type
        adjusted_confidence = base_confidence * (0.5 + type_rate * 0.5)
        if type_rate < 0.5:
            notes.append(f"Confidence reduced — {action_type} actions historically approved only {type_rate*100:.0f}% of the time")
        elif type_rate > 0.8:
            notes.append(f"High confidence — {action_type} actions approved {type_rate*100:.0f}% historically")

    adjusted_confidence = round(min(99, max(40, adjusted_confidence)), 1)
    feedback_note = " | ".join(notes) if notes else ""

    return adjusted_qty, adjusted_confidence, feedback_note


def log_feedback_run(db: Session, weights: Dict):
    """Store computed weights in audit log for transparency."""
    db.add(models.AuditLog(
        id=gen_id(),
        user_email="AI Agent",
        event_type="RETRAIN",
        entity_type="model",
        detail=f"Feedback weights updated — {weights['data_points']} decisions analyzed, approval rate {weights['approval_rate']*100:.0f}%, qty bias {weights['qty_bias']:.2f}x",
        outcome="executed",
        meta=weights
    ))
    db.commit()
    print(f"[Feedback] Weights updated: approval={weights['approval_rate']:.2f}, qty_bias={weights['qty_bias']:.2f}, threshold={weights['confidence_threshold']:.1f}")

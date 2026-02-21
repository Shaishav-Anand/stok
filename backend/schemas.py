from pydantic import BaseModel, EmailStr
from typing import Optional, List, Any
from datetime import datetime


# ── Auth ──────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_name: str
    user_email: str
    role: str


# ── SKU ───────────────────────────────────────────
class SKUCreate(BaseModel):
    sku_code: str
    name: str
    category: Optional[str] = None
    unit_cost: Optional[float] = None
    unit_price: Optional[float] = None
    reorder_point: Optional[int] = 20
    safety_stock: Optional[int] = 10
    lead_time_days: Optional[int] = 7
    moq: Optional[int] = 1

class SKUOut(BaseModel):
    id: str
    sku_code: str
    name: str
    category: Optional[str]
    unit_cost: Optional[float]
    unit_price: Optional[float]
    reorder_point: int
    safety_stock: int
    lead_time_days: int
    current_stock: Optional[int] = 0
    daily_velocity: Optional[float] = 0
    days_remaining: Optional[float] = None
    risk_level: Optional[str] = "low"
    trend: Optional[List[int]] = []

    class Config:
        from_attributes = True


# ── Inventory ──────────────────────────────────────
class InventoryUpdate(BaseModel):
    sku_code: str
    quantity: int
    location: Optional[str] = "Warehouse A"


# ── Actions ───────────────────────────────────────
class ActionApprove(BaseModel):
    quantity_override: Optional[int] = None  # manager can change qty
    notes: Optional[str] = None

class ActionReject(BaseModel):
    reason: Optional[str] = None

class ActionOut(BaseModel):
    id: str
    sku_id: str
    sku_code: Optional[str]
    sku_name: Optional[str]
    type: str
    priority: str
    title: str
    justification: Optional[str]
    risks: Optional[str]
    alternatives: Optional[str]
    recommended_qty: Optional[int]
    recommended_value: Optional[float]
    supplier_name: Optional[str]
    confidence_score: Optional[float]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Supplier ───────────────────────────────────────
class SupplierOut(BaseModel):
    id: str
    code: str
    name: str
    avg_lead_time_days: Optional[float]
    on_time_delivery_rate: Optional[float]
    quality_rate: Optional[float]
    cost_variance_pct: Optional[float]
    ai_rank: Optional[int]

    class Config:
        from_attributes = True


# ── Audit ─────────────────────────────────────────
class AuditOut(BaseModel):
    id: str
    timestamp: datetime
    user_email: Optional[str]
    event_type: str
    detail: Optional[str]
    outcome: Optional[str]

    class Config:
        from_attributes = True


# ── Forecast ──────────────────────────────────────
class ForecastOut(BaseModel):
    sku_code: str
    sku_name: str
    actual: List[dict]       # [{date, value}]
    forecast: List[dict]     # [{date, value, lower, upper}]
    model_used: str
    accuracy_pct: Optional[float]
    computed_at: Optional[datetime]


# ── CSV Upload ────────────────────────────────────
class UploadResult(BaseModel):
    rows_processed: int
    rows_inserted: int
    rows_failed: int
    errors: List[str] = []
    message: str


# ── Stats ─────────────────────────────────────────
class DashboardStats(BaseModel):
    total_skus: int
    stockout_risk_count: int
    critical_count: int
    pending_actions_count: int
    pending_value: float
    ai_accuracy: Optional[float]
    slow_movers_count: int
    slow_movers_value: float

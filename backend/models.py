from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="manager")  # manager, admin, viewer
    created_at = Column(DateTime, server_default=func.now())


class SKU(Base):
    __tablename__ = "skus"
    id = Column(String, primary_key=True, default=gen_uuid)
    sku_code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String)
    unit_cost = Column(Float)
    unit_price = Column(Float)
    reorder_point = Column(Integer, default=20)
    safety_stock = Column(Integer, default=10)
    lead_time_days = Column(Integer, default=7)
    moq = Column(Integer, default=1)           # minimum order quantity
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    inventory = relationship("Inventory", back_populates="sku", uselist=False)
    sales = relationship("SalesHistory", back_populates="sku")
    actions = relationship("PendingAction", back_populates="sku")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    contact_email = Column(String)
    api_endpoint = Column(String)        # for future API integration
    avg_lead_time_days = Column(Float)
    on_time_delivery_rate = Column(Float)   # 0-100
    quality_rate = Column(Float)             # 0-100
    cost_variance_pct = Column(Float)        # positive = more expensive
    ai_rank = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    sku_suppliers = relationship("SKUSupplier", back_populates="supplier")


class SKUSupplier(Base):
    """Links SKUs to their possible suppliers"""
    __tablename__ = "sku_suppliers"
    id = Column(String, primary_key=True, default=gen_uuid)
    sku_id = Column(String, ForeignKey("skus.id"))
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    unit_cost = Column(Float)
    lead_time_days = Column(Integer)
    moq = Column(Integer, default=1)
    is_preferred = Column(Boolean, default=False)

    supplier = relationship("Supplier", back_populates="sku_suppliers")


class Inventory(Base):
    __tablename__ = "inventory"
    id = Column(String, primary_key=True, default=gen_uuid)
    sku_id = Column(String, ForeignKey("skus.id"), unique=True)
    location = Column(String, default="Warehouse A")
    quantity = Column(Integer, default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())

    sku = relationship("SKU", back_populates="inventory")


class SalesHistory(Base):
    __tablename__ = "sales_history"
    id = Column(String, primary_key=True, default=gen_uuid)
    sku_id = Column(String, ForeignKey("skus.id"))
    date = Column(DateTime, nullable=False)
    quantity_sold = Column(Integer, nullable=False)
    revenue = Column(Float)
    channel = Column(String, default="online")   # online, retail, wholesale
    created_at = Column(DateTime, server_default=func.now())

    sku = relationship("SKU", back_populates="sales")


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id = Column(String, primary_key=True, default=gen_uuid)
    sku_id = Column(String, ForeignKey("skus.id"))
    type = Column(String, nullable=False)       # order, transfer, price, return, disposal
    priority = Column(String, default="normal") # urgent, high, normal
    title = Column(String, nullable=False)
    justification = Column(Text)
    risks = Column(Text)
    alternatives = Column(Text)
    recommended_qty = Column(Integer)
    recommended_value = Column(Float)
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=True)
    confidence_score = Column(Float)
    status = Column(String, default="pending")  # pending, approved, rejected, executed
    extra_data = Column(JSON)                   # flexible field for type-specific data
    created_at = Column(DateTime, server_default=func.now())
    reviewed_at = Column(DateTime)
    reviewed_by = Column(String, ForeignKey("users.id"), nullable=True)

    sku = relationship("SKU", back_populates="actions")
    supplier = relationship("Supplier")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(String, primary_key=True, default=gen_uuid)
    timestamp = Column(DateTime, server_default=func.now())
    user_id = Column(String, nullable=True)     # null = AI Agent
    user_email = Column(String, nullable=True)
    event_type = Column(String, nullable=False) # GENERATE, APPROVE, REJECT, EXECUTE, UPLOAD, RETRAIN
    entity_type = Column(String)                # action, sku, supplier, model
    entity_id = Column(String)
    detail = Column(Text)
    outcome = Column(String)                    # approved, rejected, modified, executed
    meta = Column(JSON)


class ForecastCache(Base):
    """Stores computed forecasts so we don't rerun ML on every request"""
    __tablename__ = "forecast_cache"
    id = Column(String, primary_key=True, default=gen_uuid)
    sku_id = Column(String, ForeignKey("skus.id"), unique=True)
    forecast_json = Column(JSON)    # {date: value} for next 30 days
    model_used = Column(String)
    accuracy_pct = Column(Float)
    computed_at = Column(DateTime, server_default=func.now())
    valid_until = Column(DateTime)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from services.auth import authenticate_user, create_access_token, hash_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({"sub": user.email})
    return schemas.TokenResponse(
        access_token=token,
        user_name=user.name,
        user_email=user.email,
        role=user.role
    )


@router.post("/register")
def register(data: schemas.LoginRequest, name: str = "Manager", db: Session = Depends(get_db)):
    """First-time setup only — register a manager account"""
    existing = db.query(models.User).filter(models.User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    import uuid
    user = models.User(
        id=str(uuid.uuid4()),
        email=data.email,
        name=name,
        hashed_password=hash_password(data.password),
        role="admin"
    )
    db.add(user)
    db.commit()
    return {"message": "Account created", "email": data.email}

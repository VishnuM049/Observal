import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from config import settings
from models.user import User, UserRole
from schemas.auth import InitRequest, InitResponse, LoginRequest, UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/init", response_model=InitResponse)
async def init_admin(req: InitRequest, db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=400, detail="System already initialized")

    api_key = secrets.token_hex(settings.API_KEY_LENGTH)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    user = User(
        email=req.email,
        name=req.name,
        role=UserRole.admin,
        api_key_hash=key_hash,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.post("/login", response_model=UserResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    key_hash = hashlib.sha256(req.api_key.encode()).hexdigest()
    result = await db.execute(select(User).where(User.api_key_hash == key_hash))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return UserResponse.model_validate(user)


@router.get("/whoami", response_model=UserResponse)
async def whoami(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

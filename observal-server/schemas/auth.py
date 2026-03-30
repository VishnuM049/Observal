import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from models.user import UserRole


class InitRequest(BaseModel):
    email: EmailStr
    name: str


class LoginRequest(BaseModel):
    api_key: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}


class InitResponse(BaseModel):
    user: UserResponse
    api_key: str

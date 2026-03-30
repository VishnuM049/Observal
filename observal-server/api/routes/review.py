import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from models.mcp import ListingStatus, McpListing
from models.user import User, UserRole
from schemas.mcp import McpListingResponse, ReviewActionRequest

router = APIRouter(prefix="/api/v1/review", tags=["review"])


def _require_admin(user: User):
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("", response_model=list[McpListingResponse])
async def list_pending(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(
        select(McpListing).where(McpListing.status == ListingStatus.pending).order_by(McpListing.created_at.desc())
    )
    return [McpListingResponse.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=McpListingResponse)
async def get_review(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(select(McpListing).where(McpListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return McpListingResponse.model_validate(listing)


@router.post("/{listing_id}/approve", response_model=McpListingResponse)
async def approve(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(select(McpListing).where(McpListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.status = ListingStatus.approved
    await db.commit()
    await db.refresh(listing)
    return McpListingResponse.model_validate(listing)


@router.post("/{listing_id}/reject", response_model=McpListingResponse)
async def reject(
    listing_id: uuid.UUID,
    req: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(select(McpListing).where(McpListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.status = ListingStatus.rejected
    listing.rejection_reason = req.reason
    await db.commit()
    await db.refresh(listing)
    return McpListingResponse.model_validate(listing)

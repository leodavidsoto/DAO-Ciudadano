"""
Dashboard Router
Handles statistics and analytics endpoints
"""
from fastapi import APIRouter, Query
from datetime import datetime, timezone, timedelta
import logging

from ..models import DashboardStats
from ..core.config import settings
from ..core.database import members_collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def active_members_query() -> dict:
    """Use the same trust boundary as membership authorization.

    Demo environments report pilot rows. Production metrics only include
    records that could actually pass the production membership gate; otherwise
    quarantined demo/legacy data would be presented as valid citizens.
    """
    query = {"status": "active"}
    if settings.is_production:
        query.update({
            "issuance_mode": "onchain",
            "identity_verified": True,
            "tx_hash": {"$type": "string", "$ne": ""},
        })
    return query


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """
    Get aggregated DAO statistics for dashboard display
    """
    try:
        member_query = active_members_query()
        total_members = await members_collection().count_documents(member_query)
        
        # Count recent joins (last 30 days)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        recent_query = {
            **member_query,
            "created_at": {"$gte": thirty_days_ago},
        }
        recent_joins = await members_collection().count_documents(recent_query)
        
        return DashboardStats(
            total_members=total_members,
            recent_joins=recent_joins,
            your_token_id=None
        )
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        return DashboardStats(total_members=0, recent_joins=0)


@router.get("/activity")
async def get_recent_activity(limit: int = Query(default=10, ge=1, le=100)):
    """
    Get recent DAO activity feed
    """
    try:
        recent_members = await members_collection().find(
            active_members_query()
        ).sort("created_at", -1).limit(limit).to_list(limit)
        
        activities = []
        for member in recent_members:
            activities.append({
                "type": "new_member",
                "wallet": member.get("wallet_address", "")[:10] + "...",
                "token_id": member.get("token_id"),
                "timestamp": member.get("created_at")
            })
        
        return {"activities": activities}
        
    except Exception as e:
        logger.error(f"Error getting activity: {e}")
        return {"activities": []}

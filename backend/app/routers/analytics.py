from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, Request, BackgroundTasks
from pydantic import BaseModel

from ..core.database import get_collection

router = APIRouter(tags=["Analytics"])

class VisitCreate(BaseModel):
    path: str
    user_agent: str | None = None
    referrer: str | None = None

async def _log_visit(visit_data: dict):
    # This runs in background
    visits = get_collection("visits")
    await visits.insert_one(visit_data)

@router.post("/visit")
async def log_visit(request: Request, visit: VisitCreate, background_tasks: BackgroundTasks):
    ip = request.client.host if request.client else "unknown"
    visit_data = {
        "path": visit.path,
        "ip": ip,
        "user_agent": visit.user_agent or request.headers.get("user-agent", ""),
        "referrer": visit.referrer,
        "timestamp": datetime.now(timezone.utc)
    }
    background_tasks.add_task(_log_visit, visit_data)
    return {"status": "ok"}

@router.get("/dashboard")
async def get_dashboard_metrics() -> Dict[str, Any]:
    visits = get_collection("visits")
    
    total_visits = await visits.count_documents({})
    
    pipeline = [
        {"$group": {"_id": "$path", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    top_paths = await visits.aggregate(pipeline).to_list(length=10)
    
    # daily visits last 7 days
    from datetime import timedelta
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    daily_pipeline = [
        {"$match": {"timestamp": {"$gte": seven_days_ago}}},
        {"$group": {
            "_id": {
                "$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    daily_visits = await visits.aggregate(daily_pipeline).to_list(length=7)
    
    return {
        "total": total_visits,
        "paths": [{"path": item["_id"], "count": item["count"]} for item in top_paths],
        "daily": [{"date": item["_id"], "count": item["count"]} for item in daily_visits]
    }

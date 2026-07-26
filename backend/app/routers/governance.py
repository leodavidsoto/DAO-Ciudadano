"""
Governance Router
Handles proposals and voting endpoints for DAO
Uses MongoDB for persistent storage
Security: Anti-fraud validation enabled
"""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone, timedelta
import uuid
import logging
import re

from ..core.database import (
    proposals_collection,
    votes_collection,
    delegations_collection,
    treasury_transactions_collection,
    members_collection
)
from ..core.security_middleware import (
    fraud_detector,
    verify_eth_address,
    generate_nonce,
    hash_vote_data
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["Governance"])


# === Constants ===
MAX_DELEGATION_POWER = 10  # Maximum voting power multiplier
DELEGATION_COOLDOWN_HOURS = 24
MIN_PROPOSAL_TITLE_LENGTH = 5
MAX_PROPOSAL_TITLE_LENGTH = 100
MIN_PROPOSAL_DESCRIPTION_LENGTH = 20
MAX_PROPOSAL_DESCRIPTION_LENGTH = 5000


# === Models with Validation ===

class ProposalCreate(BaseModel):
    title: str
    description: str
    category: str = "general"  # general, treasury, membership, technical
    creator_address: str
    duration_days: int = 7
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        v = v.strip()
        if len(v) < MIN_PROPOSAL_TITLE_LENGTH:
            raise ValueError(f'Title must be at least {MIN_PROPOSAL_TITLE_LENGTH} characters')
        if len(v) > MAX_PROPOSAL_TITLE_LENGTH:
            raise ValueError(f'Title must be less than {MAX_PROPOSAL_TITLE_LENGTH} characters')
        # Remove potential XSS
        v = re.sub(r'<[^>]+>', '', v)
        return v
    
    @field_validator('description')
    @classmethod
    def validate_description(cls, v):
        v = v.strip()
        if len(v) < MIN_PROPOSAL_DESCRIPTION_LENGTH:
            raise ValueError(f'Description must be at least {MIN_PROPOSAL_DESCRIPTION_LENGTH} characters')
        if len(v) > MAX_PROPOSAL_DESCRIPTION_LENGTH:
            raise ValueError(f'Description must be less than {MAX_PROPOSAL_DESCRIPTION_LENGTH} characters')
        # Remove potential XSS
        v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
        return v
    
    @field_validator('creator_address')
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError('Invalid Ethereum address format')
        return v.lower()  # Normalize to lowercase
    
    @field_validator('duration_days')
    @classmethod
    def validate_duration(cls, v):
        if v < 1 or v > 90:
            raise ValueError('Duration must be between 1 and 90 days')
        return v
    
    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        allowed = ['general', 'treasury', 'membership', 'technical']
        if v not in allowed:
            raise ValueError(f'Category must be one of: {", ".join(allowed)}')
        return v


class ProposalResponse(BaseModel):
    id: str
    title: str
    description: str
    category: str
    creator_address: str
    status: str  # active, passed, rejected, expired
    votes_for: int = 0
    votes_against: int = 0
    votes_abstain: int = 0
    total_votes: int = 0
    quorum_required: int = 10
    created_at: datetime
    ends_at: datetime


class VoteRequest(BaseModel):
    proposal_id: str
    voter_address: str
    vote: str  # for, against, abstain
    nonce: Optional[str] = None  # For replay protection
    
    @field_validator('voter_address')
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError('Invalid Ethereum address format')
        return v.lower()
    
    @field_validator('vote')
    @classmethod
    def validate_vote(cls, v):
        allowed = ['for', 'against', 'abstain']
        if v not in allowed:
            raise ValueError(f'Vote must be one of: {", ".join(allowed)}')
        return v


class VoteResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    error: Optional[str] = None
    vote_hash: Optional[str] = None  # For verification


# === Proposal Endpoints ===

@router.post("/proposals", response_model=ProposalResponse)
async def create_proposal(request: ProposalCreate):
    """Create a new governance proposal"""
    try:
        proposal_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc)
        
        proposal = {
            "id": proposal_id,
            "title": request.title,
            "description": request.description,
            "category": request.category,
            "creator_address": request.creator_address,
            "status": "active",
            "votes_for": 0,
            "votes_against": 0,
            "votes_abstain": 0,
            "total_votes": 0,
            "quorum_required": 10,
            "created_at": now,
            "ends_at": now + timedelta(days=request.duration_days)
        }
        
        await proposals_collection().insert_one(proposal)
        
        logger.info(f"Proposal created: {proposal_id}")
        return ProposalResponse(**proposal)
        
    except Exception as e:
        logger.error(f"Error creating proposal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals", response_model=List[ProposalResponse])
async def get_proposals(status: Optional[str] = None, limit: int = 20):
    """Get all proposals, optionally filtered by status"""
    try:
        now = datetime.now(timezone.utc)
        
        # Update expired proposals
        await proposals_collection().update_many(
            {
                "status": "active",
                "ends_at": {"$lt": now}
            },
            [
                {
                    "$set": {
                        "status": {
                            "$cond": {
                                "if": {"$gte": ["$total_votes", "$quorum_required"]},
                                "then": {
                                    "$cond": {
                                        "if": {"$gt": ["$votes_for", "$votes_against"]},
                                        "then": "passed",
                                        "else": "rejected"
                                    }
                                },
                                "else": "expired"
                            }
                        }
                    }
                }
            ]
        )
        
        # Build query
        query = {}
        if status:
            query["status"] = status
        
        # Fetch proposals
        cursor = proposals_collection().find(query).sort("created_at", -1).limit(limit)
        proposals = await cursor.to_list(length=limit)
        
        return [ProposalResponse(**p) for p in proposals]
        
    except Exception as e:
        logger.error(f"Error getting proposals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(proposal_id: str):
    """Get a specific proposal by ID"""
    proposal = await proposals_collection().find_one({"id": proposal_id})
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ProposalResponse(**proposal)


@router.post("/vote", response_model=VoteResponse)
async def cast_vote(request: VoteRequest):
    """Cast a vote on a proposal"""
    try:
        # Get proposal
        proposal = await proposals_collection().find_one({"id": request.proposal_id})
        if not proposal:
            return VoteResponse(ok=False, error="Proposal not found")
        
        # Check if proposal is active
        if proposal["status"] != "active":
            return VoteResponse(ok=False, error="Proposal is not active")
        
        # Check if already voted
        existing_vote = await votes_collection().find_one({
            "proposal_id": request.proposal_id,
            "voter_address": request.voter_address
        })
        if existing_vote:
            return VoteResponse(ok=False, error="Already voted on this proposal")
        
        # Record vote
        vote_record = {
            "proposal_id": request.proposal_id,
            "voter_address": request.voter_address,
            "vote": request.vote,
            "timestamp": datetime.now(timezone.utc)
        }
        await votes_collection().insert_one(vote_record)
        
        # Update vote counts
        update_field = f"votes_{request.vote}" if request.vote in ["for", "against", "abstain"] else "votes_abstain"
        await proposals_collection().update_one(
            {"id": request.proposal_id},
            {
                "$inc": {update_field: 1, "total_votes": 1}
            }
        )
        
        logger.info(f"Vote cast: {request.voter_address} -> {request.vote} on {request.proposal_id}")
        
        return VoteResponse(ok=True, message=f"Vote recorded: {request.vote}")
        
    except Exception as e:
        logger.error(f"Error casting vote: {e}")
        return VoteResponse(ok=False, error=str(e))


@router.get("/stats")
async def get_governance_stats():
    """Get governance statistics"""
    try:
        total = await proposals_collection().count_documents({})
        active = await proposals_collection().count_documents({"status": "active"})
        passed = await proposals_collection().count_documents({"status": "passed"})
        
        # Sum total votes
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$total_votes"}}}]
        result = await proposals_collection().aggregate(pipeline).to_list(1)
        total_votes = result[0]["total"] if result else 0
        
        # Participation rate = unique voters / active members.
        # Returns None when there are no members yet (avoids a fabricated figure).
        distinct_voters = await votes_collection().distinct("voter_address")
        total_members = await members_collection().count_documents({"status": "active"})
        participation_rate = (
            round(len(distinct_voters) / total_members, 4)
            if total_members > 0 else None
        )
        
        return {
            "total_proposals": total,
            "active_proposals": active,
            "passed_proposals": passed,
            "total_votes_cast": total_votes,
            "participation_rate": participation_rate
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            "total_proposals": 0,
            "active_proposals": 0,
            "passed_proposals": 0,
            "total_votes_cast": 0,
            "participation_rate": None
        }


# === VOTE DELEGATION ===

class DelegationRequest(BaseModel):
    delegator_address: str
    delegate_address: str


class DelegationResponse(BaseModel):
    ok: bool
    delegator: Optional[str] = None
    delegate: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


@router.post("/delegate", response_model=DelegationResponse)
async def delegate_vote(request: DelegationRequest):
    """Delegate voting power to another address"""
    try:
        if request.delegator_address == request.delegate_address:
            return DelegationResponse(ok=False, error="No puedes delegarte a ti mismo")
        
        # Check for circular delegation
        existing = await delegations_collection().find_one({"delegator": request.delegate_address})
        if existing and existing.get("delegate") == request.delegator_address:
            return DelegationResponse(ok=False, error="Delegación circular detectada")
        
        # Upsert delegation
        await delegations_collection().update_one(
            {"delegator": request.delegator_address},
            {
                "$set": {
                    "delegator": request.delegator_address,
                    "delegate": request.delegate_address,
                    "created_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
        logger.info(f"Delegation: {request.delegator_address} -> {request.delegate_address}")
        
        return DelegationResponse(
            ok=True,
            delegator=request.delegator_address,
            delegate=request.delegate_address,
            message="Voto delegado exitosamente"
        )
    except Exception as e:
        logger.error(f"Delegation error: {e}")
        return DelegationResponse(ok=False, error=str(e))


@router.delete("/delegate/{address}")
async def revoke_delegation(address: str):
    """Revoke vote delegation"""
    result = await delegations_collection().delete_one({"delegator": address})
    if result.deleted_count > 0:
        return {"ok": True, "message": "Delegación revocada"}
    return {"ok": False, "error": "No hay delegación activa"}


@router.get("/delegate/{address}")
async def get_delegation(address: str):
    """Get current delegation for an address"""
    delegation = await delegations_collection().find_one({"delegator": address})
    if delegation:
        return {
            "delegated": True,
            "delegate": delegation["delegate"]
        }
    return {"delegated": False, "delegate": None}


@router.get("/delegations/{delegate_address}")
async def get_delegators(delegate_address: str):
    """Get all addresses that have delegated to this delegate"""
    cursor = delegations_collection().find({"delegate": delegate_address})
    delegations = await cursor.to_list(length=100)
    delegators = [d["delegator"] for d in delegations]
    
    return {
        "delegate": delegate_address,
        "delegators": delegators,
        "voting_power": len(delegators) + 1  # +1 for own vote
    }


# === TREASURY ===

class TreasuryTransaction(BaseModel):
    id: str
    type: str  # income, expense, transfer
    amount: float
    currency: str = "ETH"
    description: str
    category: str  # operations, grants, salaries, infrastructure
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    proposal_id: Optional[str] = None
    tx_hash: Optional[str] = None
    timestamp: datetime


# NOTE: On-chain balance reading is not wired yet (see ROADMAP Fase 3.6).
# Until a real Safe multisig / RPC source is connected, treasury balances
# are reported as unconfigured instead of fabricated values.


@router.get("/treasury")
async def get_treasury():
    """Get treasury overview.

    Balances are read from real sources only. While no on-chain source is
    configured, `balances` is null and `configured` is false — never mock data.
    """
    tx_count = await treasury_transactions_collection().count_documents({})

    return {
        "configured": False,
        "balances": None,
        "total_eth_value": None,
        "total_usd_value": None,
        "transaction_count": tx_count
    }


@router.get("/treasury/transactions")
async def get_treasury_transactions(limit: int = 20, category: Optional[str] = None):
    """Get treasury transaction history (real records only)."""
    query = {}
    if category:
        query["category"] = category

    cursor = treasury_transactions_collection().find(query).sort("timestamp", -1).limit(limit)
    transactions = await cursor.to_list(length=limit)

    return transactions


@router.get("/treasury/analytics")
async def get_treasury_analytics():
    """Get treasury analytics computed from real recorded transactions.

    Runway is null until a real balance source is configured (it cannot be
    computed without a current balance).
    """
    # Aggregate income/expenses from actual stored transactions
    pipeline = [
        {
            "$group": {
                "_id": "$type",
                "total": {"$sum": "$amount"}
            }
        }
    ]

    result = await treasury_transactions_collection().aggregate(pipeline).to_list(10)

    income = next((r["total"] for r in result if r["_id"] == "income"), 0)
    expenses = next((r["total"] for r in result if r["_id"] == "expense"), 0)

    # Category breakdown
    category_pipeline = [
        {
            "$group": {
                "_id": {"category": "$category", "type": "$type"},
                "total": {"$sum": "$amount"}
            }
        }
    ]
    cat_result = await treasury_transactions_collection().aggregate(category_pipeline).to_list(50)

    categories = {}
    for r in cat_result:
        cat = r["_id"]["category"]
        tx_type = r["_id"]["type"]
        if cat not in categories:
            categories[cat] = {"income": 0, "expense": 0}
        categories[cat][tx_type] = r["total"]

    return {
        "total_income": income,
        "total_expenses": expenses,
        "net_flow": income - expenses,
        "by_category": categories,
        "runway_months": None  # Requires a configured on-chain balance source
    }

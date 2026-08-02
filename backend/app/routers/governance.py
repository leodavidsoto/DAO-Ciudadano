"""
Governance Router
Handles proposals and voting endpoints for DAO
Uses MongoDB for persistent storage
Security: membership gating (C-3), delegated vote weight (A-5) and
anti-fraud checks (A-4) are enforced on every mutating endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone, timedelta
from pymongo.errors import DuplicateKeyError
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
from ..core.config import settings
from ..services.governance_service import governance_service
from ..services.membership_verifier import get_membership_verifier
from ..services import ballot_service
from .deps import ensure_active_member, current_address, ensure_acts_as_self

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["Governance"])


# === Constants ===
MAX_DELEGATION_POWER = 10  # Maximum voting power multiplier
DELEGATION_COOLDOWN_HOURS = 24
MIN_PROPOSAL_TITLE_LENGTH = 5
MAX_PROPOSAL_TITLE_LENGTH = 100
MIN_PROPOSAL_DESCRIPTION_LENGTH = 20
MAX_PROPOSAL_DESCRIPTION_LENGTH = 5000
# Cota superior de cualquier `limit` público. Sin ella, un solo GET con
# ?limit=10000000 obliga al servidor a materializar la colección entera.
MAX_PAGE_SIZE = 500


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
    signature: Optional[str] = None  # EIP-712 typed-data signature (ver GET /governance/ballot-schema)

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
    weight: Optional[int] = None  # Voting power applied to this vote


class BallotEvidence(BaseModel):
    proposal_id: str
    voter_address: str
    vote: str
    weight: int
    nonce: str
    vote_hash: str
    timestamp: datetime
    signature: Optional[str] = None
    signature_scheme: Optional[str] = None
    chain_id: Optional[int] = None
    signature_valid: bool
    integrity_hash_valid: bool


# === Membership dependencies (C-3) ===
# FastAPI parses the body once; each dependency re-declares the request model
# so the membership check runs before the endpoint body executes.

async def verified_proposal_creator(request: ProposalCreate) -> ProposalCreate:
    await ensure_active_member(request.creator_address, "crear propuestas")
    return request


async def verified_voter(request: VoteRequest) -> VoteRequest:
    await ensure_active_member(request.voter_address, "votar")
    return request


# === Proposal Endpoints ===

@router.post("/proposals", response_model=ProposalResponse)
async def create_proposal(
    request: ProposalCreate = Depends(verified_proposal_creator),
    authenticated: str = Depends(current_address),
):
    """Create a new governance proposal (active members only, sesión de wallet requerida)"""
    ensure_acts_as_self(request.creator_address, authenticated, "crear propuestas")
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating proposal: {e}")
        raise HTTPException(status_code=500, detail="Error al crear la propuesta")


@router.get("/proposals", response_model=List[ProposalResponse])
async def get_proposals(
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
):
    """Get all proposals, optionally filtered by status"""
    try:
        now = datetime.now(timezone.utc)

        # Resolve proposals whose voting period ended
        expired_cursor = proposals_collection().find({
            "status": "active",
            "ends_at": {"$lt": now}
        })
        async for proposal in expired_cursor:
            if proposal.get("total_votes", 0) >= proposal.get("quorum_required", 10):
                new_status = (
                    "passed"
                    if proposal.get("votes_for", 0) > proposal.get("votes_against", 0)
                    else "rejected"
                )
            else:
                new_status = "expired"
            await proposals_collection().update_one(
                {"id": proposal["id"], "status": "active"},
                {"$set": {"status": new_status}}
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
        raise HTTPException(status_code=500, detail="Error al listar propuestas")


@router.get("/ballot-schema")
async def get_ballot_schema():
    """Types + domain EIP-712 para que el cliente arme y firme la papeleta
    con eth_signTypedData_v4 (MetaMask, wallet generada en la app móvil, etc).

    Evita que frontend/móvil mantengan una copia manual del schema
    desincronizada de lo que el backend realmente verifica en POST /vote.
    """
    return {
        "types": ballot_service.BALLOT_TYPES,
        "primaryType": "Ballot",
        "domain": ballot_service.domain(),
        "signed_ballots_required": settings.SIGNED_BALLOTS_REQUIRED,
    }


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(proposal_id: str):
    """Get a specific proposal by ID"""
    proposal = await proposals_collection().find_one({"id": proposal_id})
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ProposalResponse(**proposal)


@router.get(
    "/proposals/{proposal_id}/ballots",
    response_model=List[BallotEvidence],
)
async def get_ballot_evidence(
    proposal_id: str,
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
):
    """Return public, independently recomputable ballot evidence."""
    if not await proposals_collection().find_one({"id": proposal_id}):
        raise HTTPException(status_code=404, detail="Proposal not found")

    records = await votes_collection().find(
        {"proposal_id": proposal_id}
    ).sort("timestamp", 1).limit(limit).to_list(limit)
    evidence = []
    for record in records:
        nonce = record.get("nonce", "")
        signature = record.get("signature")
        chain_id = record.get("chain_id")
        signature_valid = False
        if signature and chain_id:
            try:
                recovered = ballot_service.recover_signer(
                    proposal_id,
                    record.get("voter_address", ""),
                    record.get("vote", ""),
                    nonce,
                    signature,
                    chain_id,
                )
                signature_valid = (
                    recovered.lower() == record.get("voter_address", "").lower()
                )
            except Exception:
                signature_valid = False

        expected_hash = hash_vote_data(
            proposal_id,
            record.get("voter_address", ""),
            record.get("vote", ""),
            nonce,
        )
        evidence.append(BallotEvidence(
            proposal_id=proposal_id,
            voter_address=record.get("voter_address", ""),
            vote=record.get("vote", ""),
            weight=record.get("weight", 1),
            nonce=nonce,
            vote_hash=record.get("vote_hash", ""),
            timestamp=record.get("timestamp"),
            signature=signature,
            signature_scheme=record.get("signature_scheme"),
            chain_id=chain_id,
            signature_valid=signature_valid,
            integrity_hash_valid=record.get("vote_hash") == expected_hash,
        ))
    return evidence


@router.post("/vote", response_model=VoteResponse)
async def cast_vote(
    request: VoteRequest = Depends(verified_voter),
    authenticated: str = Depends(current_address),
):
    """Cast a vote on a proposal.

    Weight = 1 (own vote) + active-member delegators (see GovernanceService).
    An address that delegated its vote must revoke before voting directly.

    Si SIGNED_BALLOTS_REQUIRED está activo (settings), o si el cliente envía
    `signature`, se exige una firma EIP-712 válida (ver GET
    /governance/ballot-schema) que pruebe que el dueño de voter_address
    efectivamente firmó ESTE proposal_id + ESTA elección + ESTE nonce.
    """
    ensure_acts_as_self(request.voter_address, authenticated, "votar")

    if settings.is_production and not settings.SIGNED_BALLOTS_REQUIRED:
        raise HTTPException(
            status_code=503,
            detail=(
                "La votación está bloqueada: producción requiere "
                "SIGNED_BALLOTS_REQUIRED=true."
            ),
        )
    if settings.SIGNED_BALLOTS_REQUIRED and not request.signature:
        raise HTTPException(
            status_code=422,
            detail="Esta votación requiere una papeleta firmada (EIP-712). Ver GET /governance/ballot-schema.",
        )

    # Anti-fraud: rapid-voting pattern check (A-4, wired per ROADMAP 3.4)
    suspicious, reason = await fraud_detector.check_rapid_voting(
        request.voter_address, request.proposal_id
    )
    if suspicious:
        logger.warning(f"Rapid voting blocked: {request.voter_address} ({reason})")
        raise HTTPException(
            status_code=429,
            detail="Actividad de voto sospechosa: demasiados votos en poco tiempo. Intenta más tarde."
        )

    # Delegated vote cannot also be cast directly (it would double-count)
    delegate = await governance_service.get_delegate_of(request.voter_address)
    if delegate:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Has delegado tu voto a {delegate}. "
                "Revoca la delegación para votar directamente."
            ),
        )

    try:
        # Get proposal
        proposal = await proposals_collection().find_one({"id": request.proposal_id})
        if not proposal:
            return VoteResponse(ok=False, error="Proposal not found")
        
        # Enforce the deadline here. Relying on GET /proposals to update status
        # allowed a write after ends_at when nobody had loaded the listing.
        now = datetime.now(timezone.utc)
        ends_at = proposal.get("ends_at")
        if ends_at and ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        voting_ended = not ends_at or ends_at <= now
        if proposal["status"] != "active" or voting_ended:
            if proposal["status"] == "active" and voting_ended:
                if proposal.get("total_votes", 0) >= proposal.get("quorum_required", 10):
                    closed_status = (
                        "passed"
                        if proposal.get("votes_for", 0) > proposal.get("votes_against", 0)
                        else "rejected"
                    )
                else:
                    closed_status = "expired"
                await proposals_collection().update_one(
                    {"id": request.proposal_id, "status": "active"},
                    {"$set": {"status": closed_status}},
                )
            return VoteResponse(ok=False, error="Proposal is not active")
        
        # Check if already voted
        existing_vote = await votes_collection().find_one({
            "proposal_id": request.proposal_id,
            "voter_address": request.voter_address
        })
        if existing_vote:
            return VoteResponse(ok=False, error="Already voted on this proposal")
        
        # Voting power: own vote + delegations from active members (A-5)
        weight = await governance_service.voting_power(request.voter_address)

        if request.signature:
            # El nonce firmado debe ser el mismo que se registra: si el
            # cliente no lo mandó, no hay forma de saber cuál firmó.
            if not request.nonce:
                return VoteResponse(ok=False, error="Falta el nonce de la papeleta firmada")
            await ballot_service.verify(
                request.proposal_id, request.voter_address, request.vote,
                request.nonce, request.signature,
            )
            nonce = request.nonce
        else:
            nonce = request.nonce or generate_nonce()

        # Integrity fingerprint of the ballot (recomputable por cualquiera).
        # Cuando hay `signature`, la prueba criptográfica real de autoría es
        # la firma EIP-712 verificada arriba, no este hash.
        vote_hash = hash_vote_data(
            request.proposal_id, request.voter_address, request.vote, nonce
        )

        # Record vote
        vote_record = {
            "proposal_id": request.proposal_id,
            "voter_address": request.voter_address,
            "vote": request.vote,
            "weight": weight,
            "nonce": nonce,
            "vote_hash": vote_hash,
            "timestamp": now,
            "signature": request.signature,
            "signature_scheme": "EIP-712" if request.signature else None,
            "chain_id": settings.SIWE_CHAIN_ID if request.signature else None,
        }
        try:
            await votes_collection().insert_one(vote_record)
        except DuplicateKeyError:
            return VoteResponse(ok=False, error="Already voted on this proposal")
        
        # Update vote counts by the applied weight, not by 1
        update_field = f"votes_{request.vote}" if request.vote in ["for", "against", "abstain"] else "votes_abstain"
        await proposals_collection().update_one(
            {"id": request.proposal_id},
            {
                "$inc": {update_field: weight, "total_votes": weight}
            }
        )
        
        logger.info(
            f"Vote cast: {request.voter_address} -> {request.vote} "
            f"on {request.proposal_id} (weight {weight})"
        )
        
        return VoteResponse(
            ok=True,
            message=f"Voto registrado: {request.vote} (peso {weight})",
            vote_hash=vote_hash,
            weight=weight,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error casting vote: {e}")
        return VoteResponse(ok=False, error="Error al registrar el voto")


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

    # Addresses were previously stored unvalidated and case-sensitive, which
    # silently broke lookups (see AUDIT, hallazgo N-4). Same rules as votes.
    @field_validator('delegator_address', 'delegate_address')
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError('Invalid Ethereum address format')
        return v.lower()


class DelegationResponse(BaseModel):
    ok: bool
    delegator: Optional[str] = None
    delegate: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


async def verified_delegator(request: DelegationRequest) -> DelegationRequest:
    await ensure_active_member(request.delegator_address, "delegar el voto")
    return request


@router.post("/delegate", response_model=DelegationResponse)
async def delegate_vote(
    request: DelegationRequest = Depends(verified_delegator),
    authenticated: str = Depends(current_address),
):
    """Delegate voting power to another address (active members only, sesión de wallet requerida)"""
    ensure_acts_as_self(request.delegator_address, authenticated, "delegar el voto")
    try:
        if request.delegator_address == request.delegate_address:
            return DelegationResponse(ok=False, error="No puedes delegarte a ti mismo")

        # The delegate must also be an active member: delegating to an address
        # that cannot vote would silently discard the delegator's weight.
        #
        # This goes through the same MembershipVerifier as the delegator gate.
        # A raw {status: "active"} query was weaker than the production gate,
        # so a quarantined legacy/demo row could receive delegations it could
        # never actually cast.
        verifier = get_membership_verifier()
        if not await verifier.is_member(request.delegate_address):
            return DelegationResponse(
                ok=False,
                error=(
                    f"No puedes delegar en {request.delegate_address}: "
                    "no es miembro activo de la DAO"
                ),
            )

        # Authoritative cycle check against the stored delegation graph
        # (catches a->b->c->a, not just the direct two-way cycle).
        if await governance_service.find_delegation_cycle(
            request.delegator_address, request.delegate_address
        ):
            return DelegationResponse(ok=False, error="Delegación circular detectada")

        # Cap on received delegations, enforced against the database
        delegator_count = await delegations_collection().count_documents({
            "delegate": request.delegate_address,
            "delegator": {"$ne": request.delegator_address},
        })
        if delegator_count >= MAX_DELEGATION_POWER:
            return DelegationResponse(
                ok=False,
                error=f"El delegado ya alcanzó el máximo de {MAX_DELEGATION_POWER} delegaciones",
            )

        # La profundidad de cadena y el máximo de delegados ya se comprobaron
        # arriba contra MongoDB (find_delegation_cycle y count_documents). El
        # detector en memoria duplicaba ambas con una copia del grafo que se
        # vaciaba al reiniciar; se eliminó en ROADMAP 3.8.

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delegation error: {e}")
        return DelegationResponse(ok=False, error="Error al delegar el voto")


@router.delete("/delegate/{address}")
async def revoke_delegation(address: str, authenticated: str = Depends(current_address)):
    """Revoke vote delegation (sesión de wallet requerida)"""
    ensure_acts_as_self(address, authenticated, "revocar tu delegación")
    result = await delegations_collection().delete_one({"delegator": address.lower()})
    if result.deleted_count > 0:
        return {"ok": True, "message": "Delegación revocada"}
    return {"ok": False, "error": "No hay delegación activa"}


@router.get("/delegate/{address}")
async def get_delegation(address: str):
    """Get current delegation for an address"""
    delegation = await delegations_collection().find_one({"delegator": address.lower()})
    if delegation:
        return {
            "delegated": True,
            "delegate": delegation["delegate"]
        }
    return {"delegated": False, "delegate": None}


@router.get("/delegations/{delegate_address}")
async def get_delegators(delegate_address: str):
    """Get all addresses that have delegated to this delegate.

    voting_power reflects the weight actually applied when voting:
    only delegators that are active members count (plus the own vote).
    """
    address = delegate_address.lower()
    cursor = delegations_collection().find({"delegate": address})
    delegations = await cursor.to_list(length=100)
    delegators = [d["delegator"] for d in delegations]
    active_delegators = await governance_service.get_active_delegators(address)

    return {
        "delegate": address,
        "delegators": delegators,
        "active_delegators": active_delegators,
        "voting_power": 1 + len(active_delegators)
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


@router.get("/treasury/transactions", response_model=List[TreasuryTransaction])
async def get_treasury_transactions(
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    category: Optional[str] = None,
):
    """Get treasury transaction history (real records only)."""
    query = {}
    if category:
        query["category"] = category

    # Project out `_id`: FastAPI cannot serialize a raw ObjectId, so the first
    # real transaction stored would have turned this endpoint into a 500.
    cursor = (
        treasury_transactions_collection()
        .find(query, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
    )
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

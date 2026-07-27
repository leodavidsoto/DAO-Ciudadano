"""
Elections Router
Representative elections: nomination, weighted voting, results and seated
representatives. Complements liquid delegation (both were explicitly chosen).

Lifecycle (status is derived from dates, like expired proposals):
    nominations  -> until nominations_end_at (candidacies open)
    voting       -> until voting_end_at (one weighted vote per member)
    closed       -> results final; top `seats` candidates become representatives

Membership gating (C-3) applies to running and voting. Election creation has
no creator field in the designed data model and therefore no address to gate;
restricting who can open an election is an authentication concern (Fase 1,
audit C-1).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone, timedelta
import uuid
import logging
import re

from pymongo.errors import DuplicateKeyError

from ..core.database import (
    elections_collection,
    candidacies_collection,
    election_votes_collection,
    representatives_collection,
)
from ..core.security_middleware import fraud_detector, verify_eth_address
from ..services.governance_service import governance_service
from .deps import ensure_active_member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["Elections"])


# === Constants ===
MIN_TITLE_LENGTH = 5
MAX_TITLE_LENGTH = 100
MIN_DESCRIPTION_LENGTH = 20
MAX_DESCRIPTION_LENGTH = 5000
MIN_STATEMENT_LENGTH = 20
MAX_STATEMENT_LENGTH = 3000
MAX_SEATS = 50
MAX_PHASE_DAYS = 90
MAX_TERM_MONTHS = 48


# === Models ===

class ElectionCreate(BaseModel):
    title: str
    description: str
    creator_address: str
    seats: int = Field(default=1, ge=1, le=MAX_SEATS)
    nominations_days: int = Field(default=7, ge=1, le=MAX_PHASE_DAYS)
    voting_days: int = Field(default=7, ge=1, le=MAX_PHASE_DAYS)
    term_months: int = Field(default=12, ge=1, le=MAX_TERM_MONTHS)

    @field_validator('creator_address')
    @classmethod
    def validate_creator_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError('Invalid Ethereum address format')
        return v.lower()

    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        v = v.strip()
        if len(v) < MIN_TITLE_LENGTH:
            raise ValueError(f'Title must be at least {MIN_TITLE_LENGTH} characters')
        if len(v) > MAX_TITLE_LENGTH:
            raise ValueError(f'Title must be less than {MAX_TITLE_LENGTH} characters')
        return re.sub(r'<[^>]+>', '', v)

    @field_validator('description')
    @classmethod
    def validate_description(cls, v):
        v = v.strip()
        if len(v) < MIN_DESCRIPTION_LENGTH:
            raise ValueError(f'Description must be at least {MIN_DESCRIPTION_LENGTH} characters')
        if len(v) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f'Description must be less than {MAX_DESCRIPTION_LENGTH} characters')
        return re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)


class ElectionResponse(BaseModel):
    id: str
    title: str
    description: str
    seats: int
    status: str  # nominations | voting | closed
    nominations_end_at: datetime
    voting_end_at: datetime
    term_months: int
    created_at: datetime
    candidacy_count: int = 0
    vote_count: int = 0


class CandidacyCreate(BaseModel):
    candidate_address: str
    statement: str  # The candidate's program

    @field_validator('candidate_address')
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError('Invalid Ethereum address format')
        return v.lower()

    @field_validator('statement')
    @classmethod
    def validate_statement(cls, v):
        v = v.strip()
        if len(v) < MIN_STATEMENT_LENGTH:
            raise ValueError(f'Statement must be at least {MIN_STATEMENT_LENGTH} characters')
        if len(v) > MAX_STATEMENT_LENGTH:
            raise ValueError(f'Statement must be less than {MAX_STATEMENT_LENGTH} characters')
        return re.sub(r'<[^>]+>', '', v)


class CandidacyResponse(BaseModel):
    id: str
    election_id: str
    candidate_address: str
    statement: str
    created_at: datetime


class ElectionVoteRequest(BaseModel):
    voter_address: str
    candidate_address: str

    @field_validator('voter_address', 'candidate_address')
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError('Invalid Ethereum address format')
        return v.lower()


class ElectionVoteResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    error: Optional[str] = None
    weight: Optional[int] = None


class CandidateResult(BaseModel):
    candidate_address: str
    statement: str
    votes: int
    elected: bool


class ElectionResultsResponse(BaseModel):
    election_id: str
    status: str
    seats: int
    total_votes_cast: int  # ballots (voters), not weight
    total_weight_cast: int
    final: bool  # True once the election is closed
    results: List[CandidateResult]


class RepresentativeResponse(BaseModel):
    election_id: str
    election_title: Optional[str] = None
    address: str
    votes: int
    term_start: datetime
    term_end: datetime


# === Membership dependencies (C-3) ===

async def verified_candidate(request: CandidacyCreate) -> CandidacyCreate:
    await ensure_active_member(request.candidate_address, "postularse a una elección")
    return request


async def verified_election_voter(request: ElectionVoteRequest) -> ElectionVoteRequest:
    await ensure_active_member(request.voter_address, "votar en una elección")
    return request


# === Helpers ===

async def _get_election_or_404(election_id: str) -> dict:
    election = await elections_collection().find_one({"id": election_id})
    if not election:
        raise HTTPException(status_code=404, detail="Elección no encontrada")
    # Derive status from dates (and finalize results when it closes)
    return await governance_service.sync_election_status(election)


async def _election_counts(election_id: str) -> tuple[int, int]:
    candidacy_count = await candidacies_collection().count_documents(
        {"election_id": election_id}
    )
    vote_count = await election_votes_collection().count_documents(
        {"election_id": election_id}
    )
    return candidacy_count, vote_count


async def _to_election_response(election: dict) -> ElectionResponse:
    candidacy_count, vote_count = await _election_counts(election["id"])
    return ElectionResponse(
        **{k: election[k] for k in (
            "id", "title", "description", "seats", "status",
            "nominations_end_at", "voting_end_at", "term_months", "created_at"
        )},
        candidacy_count=candidacy_count,
        vote_count=vote_count,
    )


# === Election Endpoints ===

@router.post("/elections", response_model=ElectionResponse)
async def create_election(request: ElectionCreate):
    """Open a representative election (nominations start immediately)."""
    # Same gate as proposals: opening an election is a governance action,
    # not something any address on the internet should be able to do.
    await ensure_active_member(request.creator_address, "convocar elecciones")
    now = datetime.now(timezone.utc)
    election = {
        "id": str(uuid.uuid4())[:8],
        "creator_address": request.creator_address,
        "title": request.title,
        "description": request.description,
        "seats": request.seats,
        "status": "nominations",
        "nominations_end_at": now + timedelta(days=request.nominations_days),
        "voting_end_at": now + timedelta(days=request.nominations_days + request.voting_days),
        "term_months": request.term_months,
        "created_at": now,
    }
    await elections_collection().insert_one(election)
    logger.info(f"Election created: {election['id']} ({request.seats} seat(s))")
    return await _to_election_response(election)


@router.get("/elections", response_model=List[ElectionResponse])
async def list_elections(status: Optional[str] = None, limit: int = 20):
    """List elections, most recent first, with date-derived statuses."""
    cursor = elections_collection().find({}).sort("created_at", -1).limit(100)
    elections = await cursor.to_list(length=100)

    synced = []
    for election in elections:
        election = await governance_service.sync_election_status(election)
        if status and election["status"] != status:
            continue
        synced.append(await _to_election_response(election))
        if len(synced) >= limit:
            break
    return synced


@router.get("/elections/{election_id}", response_model=ElectionResponse)
async def get_election(election_id: str):
    """Get a single election by id."""
    election = await _get_election_or_404(election_id)
    return await _to_election_response(election)


# === Candidacy Endpoints ===

@router.post("/elections/{election_id}/candidacies", response_model=CandidacyResponse)
async def create_candidacy(
    election_id: str,
    request: CandidacyCreate = Depends(verified_candidate),
):
    """Run for a seat (active members only, during the nominations phase)."""
    election = await _get_election_or_404(election_id)

    if election["status"] != "nominations":
        raise HTTPException(
            status_code=409,
            detail=(
                "El período de postulaciones de esta elección ya cerró "
                f"(estado actual: {election['status']})."
            ),
        )

    candidacy = {
        "id": str(uuid.uuid4())[:8],
        "election_id": election_id,
        "candidate_address": request.candidate_address,
        "statement": request.statement,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        await candidacies_collection().insert_one(candidacy)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Esta dirección ya está postulada en esta elección.",
        )

    logger.info(f"Candidacy: {request.candidate_address} in election {election_id}")
    return CandidacyResponse(**candidacy)


@router.get("/elections/{election_id}/candidacies", response_model=List[CandidacyResponse])
async def list_candidacies(election_id: str):
    """List candidacies for an election (registration order)."""
    await _get_election_or_404(election_id)
    cursor = candidacies_collection().find(
        {"election_id": election_id}
    ).sort("created_at", 1)
    candidacies = await cursor.to_list(length=1000)
    return [CandidacyResponse(**c) for c in candidacies]


# === Election Voting ===

@router.post("/elections/{election_id}/vote", response_model=ElectionVoteResponse)
async def vote_in_election(
    election_id: str,
    request: ElectionVoteRequest = Depends(verified_election_voter),
):
    """Vote for a candidate. One ballot per member, weighted by delegations."""
    election = await _get_election_or_404(election_id)

    if election["status"] != "voting":
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta elección no está en período de votación "
                f"(estado actual: {election['status']})."
            ),
        )

    # Anti-fraud: same rapid-voting heuristic as proposal votes (A-4)
    suspicious, reason = fraud_detector.check_rapid_voting(
        request.voter_address, f"election:{election_id}"
    )
    if suspicious:
        logger.warning(f"Rapid election voting blocked: {request.voter_address} ({reason})")
        raise HTTPException(
            status_code=429,
            detail="Actividad de voto sospechosa: demasiados votos en poco tiempo. Intenta más tarde."
        )

    # A delegated vote travels with the delegate; revoke to vote directly
    delegate = await governance_service.get_delegate_of(request.voter_address)
    if delegate:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Has delegado tu voto a {delegate}. "
                "Revoca la delegación para votar directamente."
            ),
        )

    candidacy = await candidacies_collection().find_one({
        "election_id": election_id,
        "candidate_address": request.candidate_address,
    })
    if not candidacy:
        return ElectionVoteResponse(
            ok=False,
            error="La dirección elegida no es candidata en esta elección.",
        )

    existing = await election_votes_collection().find_one({
        "election_id": election_id,
        "voter_address": request.voter_address,
    })
    if existing:
        return ElectionVoteResponse(
            ok=False,
            error="Ya votaste en esta elección.",
        )

    weight = await governance_service.voting_power(request.voter_address)

    vote = {
        "id": str(uuid.uuid4())[:8],
        "election_id": election_id,
        "voter_address": request.voter_address,
        "candidate_address": request.candidate_address,
        "weight": weight,
        "timestamp": datetime.now(timezone.utc),
    }
    try:
        await election_votes_collection().insert_one(vote)
    except DuplicateKeyError:
        return ElectionVoteResponse(ok=False, error="Ya votaste en esta elección.")

    logger.info(
        f"Election vote: {request.voter_address} -> {request.candidate_address} "
        f"in {election_id} (weight {weight})"
    )
    return ElectionVoteResponse(
        ok=True,
        message=f"Voto registrado (peso {weight})",
        weight=weight,
    )


# === Results & Representatives ===

@router.get("/elections/{election_id}/results", response_model=ElectionResultsResponse)
async def get_election_results(election_id: str):
    """Standings ordered by weighted votes; the top `seats` are elected.

    Ties are broken by earlier candidacy (first to register), then by
    address — deterministic and recomputable by anyone from stored data.
    Results are provisional (`final: false`) until the election closes.
    """
    election = await _get_election_or_404(election_id)
    results = await governance_service.compute_results(election_id)

    ballots = await election_votes_collection().count_documents(
        {"election_id": election_id}
    )
    total_weight = sum(r["votes"] for r in results)
    final = election["status"] == "closed"

    # Seats go to the top `seats` candidates WITH votes (zero-vote candidates
    # are never "elected", even if seats remain unfilled).
    elected_addresses = {
        r["candidate_address"]
        for r in results[: election["seats"]]
        if r["votes"] > 0
    }

    return ElectionResultsResponse(
        election_id=election_id,
        status=election["status"],
        seats=election["seats"],
        total_votes_cast=ballots,
        total_weight_cast=total_weight,
        final=final,
        results=[
            CandidateResult(
                candidate_address=r["candidate_address"],
                statement=r["statement"],
                votes=r["votes"],
                elected=r["candidate_address"] in elected_addresses,
            )
            for r in results
        ],
    )


@router.get("/representatives", response_model=List[RepresentativeResponse])
async def list_representatives():
    """Representatives whose term is currently in force."""
    # Sync any election that should have closed but was never read again
    stale_cursor = elections_collection().find({
        "status": {"$ne": "closed"},
        "voting_end_at": {"$lt": datetime.now(timezone.utc)},
    })
    async for election in stale_cursor:
        await governance_service.sync_election_status(election)

    now = datetime.now(timezone.utc)
    cursor = representatives_collection().find({
        "term_start": {"$lte": now},
        "term_end": {"$gt": now},
    }).sort("votes", -1)
    reps = await cursor.to_list(length=200)

    titles = {}
    for rep in reps:
        if rep["election_id"] not in titles:
            election = await elections_collection().find_one({"id": rep["election_id"]})
            titles[rep["election_id"]] = election["title"] if election else None

    return [
        RepresentativeResponse(
            election_id=rep["election_id"],
            election_title=titles.get(rep["election_id"]),
            address=rep["address"],
            votes=rep["votes"],
            term_start=rep["term_start"],
            term_end=rep["term_end"],
        )
        for rep in reps
    ]

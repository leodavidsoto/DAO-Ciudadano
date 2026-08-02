"""
Elections Router
Representative elections: nomination, weighted voting, results and seated
representatives. Complements liquid delegation (both were explicitly chosen).

Lifecycle (status is derived from dates, like expired proposals):
    nominations  -> until nominations_end_at (candidacies open)
    voting       -> until voting_end_at (one weighted vote per member)
    closed       -> results final; top `seats` candidates become representatives

Every mutating action requires both an active membership and a SIWE session
for the same wallet declared in the request body. Membership alone is not
authentication: without the session check, an attacker could act as any
member by copying their public address.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone, timedelta
import uuid
import logging
import re

from pymongo.errors import DuplicateKeyError

from ..core.config import settings
from ..core.database import (
    elections_collection,
    candidacies_collection,
    election_votes_collection,
    representatives_collection,
)
from ..core.security_middleware import fraud_detector, verify_eth_address
from ..services import ballot_service
from ..services.governance_service import governance_service
from .deps import current_address, ensure_active_member, ensure_acts_as_self

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
MAX_PAGE_SIZE = 200
# Cuántas elecciones se leen antes de filtrar por estado derivado de fechas.
MAX_SCAN = 200


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
    # Papeleta firmada EIP-712 (ROADMAP 3.2/3.3). Ver
    # GET /governance/elections/ballot-schema.
    nonce: Optional[str] = None
    signature: Optional[str] = None

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

async def verified_candidate(
    request: CandidacyCreate,
    authenticated: str = Depends(current_address),
) -> CandidacyCreate:
    ensure_acts_as_self(
        request.candidate_address,
        authenticated,
        "postularte a una elección",
    )
    await ensure_active_member(request.candidate_address, "postularse a una elección")
    return request


async def verified_election_voter(
    request: ElectionVoteRequest,
    authenticated: str = Depends(current_address),
) -> ElectionVoteRequest:
    ensure_acts_as_self(
        request.voter_address,
        authenticated,
        "votar en una elección",
    )
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


async def _counts_by_election(election_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Candidacy/vote totals for many elections in two aggregations.

    Listing elections used to run two count_documents() per election, so a
    page of 100 elections meant 200 round trips on a public endpoint.
    """
    if not election_ids:
        return {}

    async def _group(collection) -> dict[str, int]:
        rows = await collection().aggregate([
            {"$match": {"election_id": {"$in": election_ids}}},
            {"$group": {"_id": "$election_id", "n": {"$sum": 1}}},
        ]).to_list(length=len(election_ids))
        return {row["_id"]: row["n"] for row in rows}

    candidacies = await _group(candidacies_collection)
    votes = await _group(election_votes_collection)
    return {
        election_id: (candidacies.get(election_id, 0), votes.get(election_id, 0))
        for election_id in election_ids
    }


def _build_election_response(
    election: dict,
    candidacy_count: int,
    vote_count: int,
) -> ElectionResponse:
    return ElectionResponse(
        **{k: election[k] for k in (
            "id", "title", "description", "seats", "status",
            "nominations_end_at", "voting_end_at", "term_months", "created_at"
        )},
        candidacy_count=candidacy_count,
        vote_count=vote_count,
    )


async def _to_election_response(election: dict) -> ElectionResponse:
    candidacy_count, vote_count = await _election_counts(election["id"])
    return _build_election_response(election, candidacy_count, vote_count)


# === Election Endpoints ===

@router.post("/elections", response_model=ElectionResponse)
async def create_election(
    request: ElectionCreate,
    authenticated: str = Depends(current_address),
):
    """Open a representative election (nominations start immediately)."""
    # Same gate as proposals: opening an election is a governance action,
    # not something any address on the internet should be able to do.
    ensure_acts_as_self(
        request.creator_address,
        authenticated,
        "convocar una elección",
    )
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
async def list_elections(
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
):
    """List elections, most recent first, with date-derived statuses."""
    cursor = elections_collection().find({}).sort("created_at", -1).limit(MAX_SCAN)
    elections = await cursor.to_list(length=MAX_SCAN)

    # Status is derived from dates, so the filter can only be applied after
    # syncing; the counts are then fetched for the selected page only.
    selected = []
    for election in elections:
        election = await governance_service.sync_election_status(election)
        if status and election["status"] != status:
            continue
        selected.append(election)
        if len(selected) >= limit:
            break

    counts = await _counts_by_election([e["id"] for e in selected])
    return [
        _build_election_response(election, *counts.get(election["id"], (0, 0)))
        for election in selected
    ]


# IMPORTANTE: esta ruta literal debe declararse ANTES de
# /elections/{election_id}. FastAPI resuelve por orden de registro, así que al
# revés "ballot-schema" se interpreta como un id de elección y devuelve 404.
@router.get("/elections/ballot-schema")
async def get_election_ballot_schema():
    """Types + domain EIP-712 de la papeleta de elección.

    Se sirve desde aquí para que frontend y móvil no mantengan una copia
    manual que se desincronice de lo que el backend verifica realmente.

    `primaryType` es "ElectionBallot", distinto del "Ballot" de las
    propuestas: el structHash incluye el nombre del tipo, así que una firma no
    vale en el otro contexto.
    """
    return {
        "types": ballot_service.ELECTION_BALLOT_TYPES,
        "primaryType": "ElectionBallot",
        "domain": ballot_service.domain(),
        "signed_ballots_required": settings.SIGNED_BALLOTS_REQUIRED,
    }


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
    # Producción exige papeleta firmada. Antes esto era un 503 incondicional
    # porque las elecciones no tenían firma; ahora la tienen, así que el
    # bloqueo pasa a depender de que la exigencia esté activada.
    if settings.is_production and not settings.SIGNED_BALLOTS_REQUIRED:
        raise HTTPException(
            status_code=503,
            detail=(
                "El voto en elecciones está bloqueado: producción requiere "
                "SIGNED_BALLOTS_REQUIRED=true."
            ),
        )
    if settings.SIGNED_BALLOTS_REQUIRED and not request.signature:
        raise HTTPException(
            status_code=422,
            detail=(
                "Esta elección requiere una papeleta firmada (EIP-712). "
                "Ver GET /governance/elections/ballot-schema."
            ),
        )

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
    suspicious, reason = await fraud_detector.check_rapid_voting(
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

    if request.signature:
        # El nonce firmado tiene que ser el que se registra: si el cliente no
        # lo manda, no hay forma de saber cuál firmó.
        if not request.nonce:
            return ElectionVoteResponse(
                ok=False, error="Falta el nonce de la papeleta firmada"
            )
        await ballot_service.verify_election_ballot(
            election_id,
            request.voter_address,
            request.candidate_address,
            request.nonce,
            request.signature,
        )

    vote = {
        "id": str(uuid.uuid4())[:8],
        "election_id": election_id,
        "voter_address": request.voter_address,
        "candidate_address": request.candidate_address,
        "weight": weight,
        "timestamp": datetime.now(timezone.utc),
        # Se persisten para que cualquiera pueda reverificar el resultado sin
        # confiar en el servidor (criterio de aceptación de 3.2).
        "nonce": request.nonce,
        "signature": request.signature,
        "signature_scheme": "EIP-712" if request.signature else None,
        "chain_id": settings.SIWE_CHAIN_ID if request.signature else None,
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

    # One $in query instead of one lookup per representative.
    election_ids = list({rep["election_id"] for rep in reps})
    titles = {}
    if election_ids:
        elections = await elections_collection().find(
            {"id": {"$in": election_ids}}, {"id": 1, "title": 1}
        ).to_list(length=len(election_ids))
        titles = {e["id"]: e.get("title") for e in elections}

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


# === Papeletas verificables (ROADMAP 3.2) ====================================


class ElectionBallotEvidence(BaseModel):
    election_id: str
    voter_address: str
    candidate_address: str
    weight: int
    nonce: Optional[str] = None
    timestamp: datetime
    signature: Optional[str] = None
    signature_scheme: Optional[str] = None
    chain_id: Optional[int] = None
    signature_valid: bool


@router.get(
    "/elections/{election_id}/ballots",
    response_model=List[ElectionBallotEvidence],
)
async def get_election_ballot_evidence(
    election_id: str,
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
):
    """Papeletas públicas, recomputables por cualquiera.

    Es lo que hace que el resultado no dependa de confiar en el servidor: con
    estos datos, un tercero recupera el firmante de cada papeleta y suma los
    pesos por su cuenta.
    """
    await _get_election_or_404(election_id)

    records = await election_votes_collection().find(
        {"election_id": election_id}
    ).sort("timestamp", 1).limit(limit).to_list(limit)

    evidence = []
    for record in records:
        signature = record.get("signature")
        chain_id = record.get("chain_id")
        signature_valid = False
        if signature and chain_id:
            try:
                recovered = ballot_service.recover_election_signer(
                    election_id,
                    record.get("voter_address", ""),
                    record.get("candidate_address", ""),
                    record.get("nonce", ""),
                    signature,
                    chain_id,
                )
                signature_valid = (
                    recovered.lower() == record.get("voter_address", "").lower()
                )
            except Exception:
                signature_valid = False

        evidence.append(ElectionBallotEvidence(
            election_id=election_id,
            voter_address=record.get("voter_address", ""),
            candidate_address=record.get("candidate_address", ""),
            weight=record.get("weight", 1),
            nonce=record.get("nonce"),
            timestamp=record.get("timestamp"),
            signature=signature,
            signature_scheme=record.get("signature_scheme"),
            chain_id=chain_id,
            signature_valid=signature_valid,
        ))
    return evidence

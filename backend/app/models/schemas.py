"""
Pydantic Models for DAO Ciudadana
Data validation and serialization schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid


# === Base Models ===

class TimestampMixin(BaseModel):
    """Mixin for timestamp fields"""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None


# === Status Models ===

class StatusCheckCreate(BaseModel):
    client_name: str


class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# === Identity Models ===

class ClaveUnicaRequest(BaseModel):
    rut: str


class ClaveUnicaResponse(BaseModel):
    ok: bool
    subject_id: Optional[str] = None
    assurance_level: Optional[str] = None
    error: Optional[str] = None


class NFCRequest(BaseModel):
    """Optional payload: real chip serial captured by the mobile app.

    When absent (web demo flow), the backend generates a demo serial.
    """
    chip_serial: Optional[str] = Field(default=None, max_length=64)


class NFCResponse(BaseModel):
    ok: bool
    chip_serial: Optional[str] = None
    doc_hash: Optional[str] = None
    error: Optional[str] = None


class LivenessResponse(BaseModel):
    ok: bool
    score: Optional[float] = None
    analysis: Optional[str] = None
    error: Optional[str] = None


class IdentityEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    event_type: str  # "clave_unica", "nfc", "liveness", "rut_email"
    hash_value: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verifier: str


# === User Models (RUT + Email registration) ===

class UserRegisterRequest(BaseModel):
    """Request model for user registration with RUT and email"""
    rut: str
    email: str
    nombre: str
    apellido: str


class UserLoginRequest(BaseModel):
    """Request model for user login"""
    rut: str
    email: str


class User(BaseModel):
    """User model stored in database.

    rut/email/nombre/apellido are stored ENCRYPTED (app.core.crypto), so they
    cannot be queried directly. `rut_key` and `email_key` are blind indexes
    (app.core.identity.lookup_key) used for uniqueness checks and login.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rut: str          # encrypted
    email: str        # encrypted
    nombre: str       # encrypted
    apellido: str     # encrypted
    rut_key: Optional[str] = None      # blind index
    email_key: Optional[str] = None    # blind index
    verified: bool = False
    status: str = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None


class UserResponse(BaseModel):
    """Response model for user operations"""
    ok: bool
    user_id: Optional[str] = None
    rut: Optional[str] = None
    email: Optional[str] = None
    nombre: Optional[str] = None
    subject_id: Optional[str] = None  # For compatibility with existing flow
    assurance_level: Optional[str] = None
    error: Optional[str] = None


# === Wallet Models ===

class WalletConnectResponse(BaseModel):
    ok: bool
    address: Optional[str] = None
    error: Optional[str] = None


# === Membership Models ===

class MintSBTRequest(BaseModel):
    wallet_address: str
    assurance_level: str
    doc_hash: str


class MintSBTResponse(BaseModel):
    ok: bool
    token_id: Optional[int] = None
    tx_hash: Optional[str] = None
    error: Optional[str] = None


class Member(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wallet_address: str
    token_id: int
    # Set only when the membership was minted on-chain. Null in demo mode:
    # never fabricate a transaction hash (audit finding C-2).
    tx_hash: Optional[str] = None
    doc_hash: str
    assurance_level: str
    status: str = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# === Dashboard Models ===

class DashboardStats(BaseModel):
    total_members: int
    recent_joins: int
    your_token_id: Optional[int] = None


# === Governance Models (New) ===

class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    proposer_address: str
    status: str = "active"  # active, passed, rejected, executed
    votes_for: int = 0
    votes_against: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ends_at: Optional[datetime] = None


class Vote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proposal_id: str
    voter_address: str
    vote: bool  # True = for, False = against
    weight: int = 1
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

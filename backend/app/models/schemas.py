"""
Pydantic Models for DAO Ciudadana
Data validation and serialization schemas
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime, timezone
import uuid


# === Base Models ===


class TimestampMixin(BaseModel):
    """Mixin for timestamp fields"""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None


# === Identity Models ===


class ClaveUnicaRequest(BaseModel):
    rut: str


class ClaveUnicaResponse(BaseModel):
    ok: bool
    subject_id: Optional[str] = None
    assurance_level: Optional[str] = None
    error: Optional[str] = None


# NFCRequest/NFCResponse se eliminaron con el simulador de NFC (ROADMAP 5.8).
# Describían un `chip_serial` que el cliente elegía y un `doc_hash` derivado de
# él: campos de una verificación que no ocurría. La lectura real usa
# `app/routers/cedula.py`, cuyo esquema son los bytes del chip.


class LivenessResponse(BaseModel):
    ok: bool
    score: Optional[float] = None
    analysis: Optional[str] = None
    error: Optional[str] = None


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

    rut/email/nombre/apellido se guardan CIFRADOS (app/core/crypto.py) —
    nunca en texto plano. rut_key/email_key son índices ciegos
    (app/core/identity.lookup_key) que sí son determinísticos y permiten
    buscar por RUT/email sin descifrar toda la colección.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rut: str  # cifrado
    rut_key: str  # índice ciego, determinístico
    email: str  # cifrado
    email_key: str  # índice ciego, determinístico
    nombre: str  # cifrado
    apellido: str  # cifrado
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
    token_id: Optional[int] = None
    # Las membresías emitidas por la vía ZK NO tienen doc_hash: el documento
    # nunca llega al servidor, que es justamente el objetivo del rediseño.
    # Inventar uno para rellenar el modelo sería fabricar un dato.
    doc_hash: Optional[str] = None
    assurance_level: str = "ZK_VERIFIED"
    # Nullifier que autorizó el minteo ZK. Es público y no revela identidad.
    nullifier_hash: Optional[str] = None
    status: str = "active"
    # Explicit provenance keeps demo/legacy rows from becoming trusted merely
    # because the same MongoDB database is later promoted to production.
    issuance_mode: Literal["demo", "onchain", "legacy_unverified"] = "legacy_unverified"
    # Solo la vía ZK puede ponerlo en True: el contrato únicamente acepta
    # raíces que el emisor aprobó tras consumir un grant civil de un solo uso.
    # El minteo demo nunca lo hace.
    identity_verified: bool = False
    tx_hash: Optional[str] = (
        None  # None en modo demo; hash real si se minteó on-chain (task 1.5)
    )
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

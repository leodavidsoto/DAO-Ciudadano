"""
Session endpoints: prove control of a wallet, get a token (ROADMAP 1.1).

Replaces the RUT+email login, which authenticated with two pieces of public
information (audit finding C-6).
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from ..core.security_middleware import verify_eth_address
from ..services.siwe_service import siwe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/session", tags=["Session"])


class ChallengeRequest(BaseModel):
    address: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError("Invalid Ethereum address format")
        return v.lower()


class ChallengeResponse(BaseModel):
    address: str
    nonce: str
    message: str
    expires_in: int


class VerifyRequest(BaseModel):
    address: str
    signature: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, v):
        if not verify_eth_address(v):
            raise ValueError("Invalid Ethereum address format")
        return v.lower()


class VerifyResponse(BaseModel):
    ok: bool
    token: str | None = None
    address: str | None = None
    error: str | None = None


@router.post("/challenge", response_model=ChallengeResponse)
async def create_challenge(request: ChallengeRequest):
    """Issue a nonce for `address` to sign."""
    challenge = await siwe_service.create_challenge(request.address)
    return ChallengeResponse(**{
        "address": challenge["address"],
        "nonce": challenge["nonce"],
        "message": challenge["message"],
        "expires_in": challenge["expires_in"],
    })


@router.post("/verify", response_model=VerifyResponse)
async def verify_challenge(request: VerifyRequest):
    """Exchange a signed challenge for a session token."""
    ok, token, error = await siwe_service.verify(request.address, request.signature)
    if not ok:
        return VerifyResponse(ok=False, error=error)

    logger.info(f"Session issued for {request.address}")
    return VerifyResponse(ok=True, token=token, address=request.address)

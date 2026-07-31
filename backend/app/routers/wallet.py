"""
Wallet Router — sesión de wallet vía SIWE (ver services/siwe_service.py).

Antes: POST /wallet/connect devolvía una dirección MOCK inventada por el
servidor, sin que el cliente hubiera probado controlar ninguna wallet
real. Cualquier código que confiara en esa dirección para autenticar algo
estaba confiando en un valor que el propio backend se inventó.

Ahora: challenge/verify de dos pasos. El cliente pide un desafío para SU
dirección real, lo firma con personal_sign desde su wallet (MetaMask,
wallet generada en la app móvil, etc.), y solo si la firma es válida se
emite un JWT de sesión.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import asyncio

from ..models import WalletConnectResponse
from ..core.security import generate_mock_address
from ..services import siwe_service
from ..core import readiness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.post("/connect", response_model=WalletConnectResponse, deprecated=True)
async def connect_wallet_mock():
    """DEPRECADO: dirección inventada por el servidor, no autentica nada.

    Se mantiene solo mientras frontend/src/context/OnboardingContext.jsx
    migra a POST /wallet/challenge + /wallet/verify (SIWE real). No usar
    esta dirección para autorizar ninguna acción -- nadie probó
    controlarla.
    """
    try:
        await asyncio.sleep(0.08)
        address = generate_mock_address()
        return WalletConnectResponse(ok=True, address=address)
    except Exception as e:
        logger.error(f"Error connecting wallet (mock): {e}")
        return WalletConnectResponse(ok=False, error=str(e))


class ChallengeRequest(BaseModel):
    address: str


class ChallengeResponse(BaseModel):
    message: str
    nonce: str


class VerifyRequest(BaseModel):
    address: str
    nonce: str
    signature: str


class VerifyResponse(BaseModel):
    token: str
    address: str
    expires_in: int


@router.post("/challenge", response_model=ChallengeResponse)
async def challenge(request: ChallengeRequest):
    """Genera un desafío SIWE de un solo uso para que el cliente lo firme."""
    if not request.address or not request.address.startswith("0x") or len(request.address) != 42:
        raise HTTPException(status_code=422, detail="Dirección Ethereum inválida.")
    result = await siwe_service.create_challenge(request.address)
    return ChallengeResponse(**result)


@router.post("/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest):
    """Verifica la firma del desafío y emite un JWT de sesión."""
    readiness.require("SECRET_KEY", "iniciar sesión con tu wallet")
    address = await siwe_service.verify(request.address, request.nonce, request.signature)
    token = siwe_service.issue_token(address)
    from ..core.config import settings
    return VerifyResponse(token=token, address=address, expires_in=settings.SESSION_TOKEN_EXPIRE_SECONDS)


@router.get("/balance/{address}")
async def get_wallet_balance(address: str):
    """
    Get wallet balance and token holdings

    Future: Query actual blockchain for ETH/token balances
    """
    return {
        "address": address,
        "eth_balance": "0.0",
        "sbt_count": 0,
        "network": "mock"
    }

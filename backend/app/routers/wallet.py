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

El JWT se entrega por dos vías (tarea 1.13):
- cookie `HttpOnly` + cookie CSRF legible, siempre — es lo que usa la web y
  lo que saca la sesión de `localStorage`;
- campo `token` del body, salvo que el cliente pida `session_transport:
  "cookie"`. La app móvil no tiene cookies de navegador y lo sigue usando.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from eth_utils import is_address
from pydantic import BaseModel
from typing import Literal, Optional

from ..core import readiness, session
from ..core.config import settings
from ..services import siwe_service
from .deps import current_address

router = APIRouter(prefix="/wallet", tags=["Wallet"])


class ChallengeRequest(BaseModel):
    address: str


class ChallengeResponse(BaseModel):
    message: str
    nonce: str


class VerifyRequest(BaseModel):
    address: str
    nonce: str
    signature: str
    # "token": compatible con la app móvil (el JWT viaja también en el body).
    # "cookie": el body no lleva el JWT; la sesión vive solo en la cookie
    # HttpOnly, así que ni siquiera existe una copia que un XSS pueda leer.
    session_transport: Literal["token", "cookie"] = "token"


class VerifyResponse(BaseModel):
    address: str
    expires_in: int
    csrf_token: str
    token: Optional[str] = None


class SessionResponse(BaseModel):
    address: str
    csrf_token: str


@router.post("/challenge", response_model=ChallengeResponse)
async def challenge(request: ChallengeRequest):
    """Genera un desafío SIWE de un solo uso para que el cliente lo firme."""
    readiness.require("SECRET_KEY", "iniciar sesión con tu wallet")
    readiness.require_siwe_configuration()
    if not is_address(request.address):
        raise HTTPException(status_code=422, detail="Dirección Ethereum inválida.")
    result = await siwe_service.create_challenge(request.address)
    return ChallengeResponse(**result)


@router.post("/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest, response: Response):
    """Verifica la firma del desafío, emite el JWT y fija la cookie de sesión."""
    readiness.require("SECRET_KEY", "iniciar sesión con tu wallet")
    readiness.require_siwe_configuration()
    address = await siwe_service.verify(
        request.address, request.nonce, request.signature
    )
    token = siwe_service.issue_token(address)
    csrf_token = session.attach_session(response, token)
    return VerifyResponse(
        token=token if request.session_transport == "token" else None,
        address=address,
        expires_in=settings.SESSION_TOKEN_EXPIRE_SECONDS,
        csrf_token=csrf_token,
    )


@router.get("/session", response_model=SessionResponse)
async def read_session(request: Request, authenticated: str = Depends(current_address)):
    """Quién es la sesión actual. 401 si no hay ninguna válida.

    Con la cookie en `HttpOnly` el cliente ya no puede mirar el JWT para
    saber si sigue conectado ni qué dirección es: tiene que preguntarlo.
    Devuelve también el token CSRF por si la cookie no fuera legible (otro
    subdominio, un navegador que la bloquee).
    """
    token, _ = session.token_from_request(request, request.headers.get("authorization"))
    return SessionResponse(
        address=authenticated,
        csrf_token=session.csrf_token_for(token) if token else "",
    )


@router.post("/logout")
async def logout(response: Response):
    """Borra las cookies de sesión.

    Deliberadamente sin autenticación: cerrar sesión con una cookie ya
    expirada o corrupta tiene que funcionar igual, y no hay nada que
    proteger — el único efecto es dejar de mandar credenciales.

    Honestidad sobre el alcance: el JWT sigue siendo válido hasta que expire
    (SESSION_TOKEN_EXPIRE_SECONDS). Esto cierra la sesión del navegador, no
    revoca el token; una lista de revocación necesita almacenamiento
    compartido y todavía no existe.
    """
    session.clear_session(response)
    return {"ok": True, "message": "Sesión cerrada en este navegador."}

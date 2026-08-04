"""
Identity Router — emisión de credenciales ZK (ADR-001, D-2).

Vive fuera de `auth.py` **a propósito**. Ese router aplica
`require_non_production_identity_demo` a nivel de router para apagar los
simuladores de ClaveÚnica/NFC/liveness en producción. Este endpoint es lo
contrario: es el camino real, y debe funcionar precisamente en producción.
Colgarlo del mismo router lo habría dejado devolviendo 503 justo donde tiene
que servir, y moverlo fuera de ese router habría sido fácil de deshacer sin
darse cuenta en un refactor. Separado en su propio módulo, la distinción es
estructural.

Lo que sí exige, y falla cerrado si falta:
  - sesión SIWE que pertenezca exactamente a la wallet declarada;
  - grant civil de un solo uso emitido por un proveedor real;
  - emisor configurado (IDENTITY_ISSUER_PRIVATE_KEY);
  - contrato accesible para leer el scope y aprobar la raíz.
"""
import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, field_validator

from typing import Optional

from ..core.config import settings
from ..core.poseidon import FIELD
from ..services import clave_unica, identity_grant, identity_issuer
from .deps import current_address, ensure_acts_as_self

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Identity"])


def _field_element(value: str, label: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} debe ser un entero decimal.")
    if parsed <= 0 or parsed >= FIELD:
        raise ValueError(f"{label} está fuera del campo escalar BN254.")
    return parsed


class IdentityCredentialRequest(BaseModel):
    wallet_address: str
    identity_commitment: str
    membership_scope: str
    membership_contract: str
    chain_id: str
    identity_grant: str

    @field_validator("identity_commitment")
    @classmethod
    def validate_commitment(cls, v):
        _field_element(v, "identity_commitment")
        return v

    @field_validator("membership_scope")
    @classmethod
    def validate_scope(cls, v):
        _field_element(v, "membership_scope")
        return v


BINDING_COOKIE_ALIAS = settings.CLAVE_UNICA_BINDING_COOKIE_NAME


@router.post("/identity-credential")
async def issue_identity_credential(
    request: IdentityCredentialRequest,
    authenticated: str = Depends(current_address),
    binding: Optional[str] = Cookie(default=None, alias=BINDING_COOKIE_ALIAS),
):
    """Emite la credencial firmada con su ruta Merkle.

    El commitment lo calcula el cliente: el backend nunca ve `identitySecret`.
    """
    # La credencial queda ligada a esta wallet dentro de la hoja del árbol, así
    # que pedirla "para" otra dirección sería emitir una credencial que su
    # dueño legítimo no podría usar.
    ensure_acts_as_self(
        request.wallet_address, authenticated, "solicitar una credencial de identidad"
    )

    if settings.is_production and not identity_grant.provider_is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "No hay proveedor de identidad civil configurado. La emisión de "
                "credenciales está deshabilitada hasta integrarlo."
            ),
        )

    # La red declarada debe ser la que este backend opera.
    if str(request.chain_id).strip() != str(settings.SIWE_CHAIN_ID):
        raise HTTPException(
            status_code=422,
            detail="La red declarada no corresponde a la que opera este servicio.",
        )

    expected_contract = settings.SBT_CONTRACT_ADDRESS.strip().lower()
    if not expected_contract:
        raise HTTPException(
            status_code=503,
            detail="El contrato de membresía no está configurado en el servidor.",
        )
    if request.membership_contract.strip().lower() != expected_contract:
        raise HTTPException(
            status_code=422,
            detail="El contrato declarado no corresponde al configurado en el servidor.",
        )

    # Tercera barrera, ADEMÁS de SIWE y CSRF: el grant se canjea solo desde el
    # navegador que se identificó ante ClaveÚnica. Copiar el bearer de sesión
    # a otro navegador, o el grant a otro cliente, falla aquí — antes de emitir
    # nada. Los grants antiguos sin binding siguen canjeándose igual: exigirlo
    # retroactivamente dejaría a esas personas sin credencial.
    try:
        credential = await identity_issuer.issue_credential(
            wallet_address=request.wallet_address,
            identity_commitment=int(request.identity_commitment),
            membership_scope=int(request.membership_scope),
            grant=request.identity_grant,
            browser_binding=(
                clave_unica.hash_browser_binding(binding) if binding else None
            ),
        )
    except identity_grant.IdentityGrantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except identity_issuer.IdentityIssuanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # No se registra el grant, la firma, la ruta ni dato civil alguno.
    logger.info("Identity credential issued (leaf root published on-chain)")

    return {"ok": True, "identity": credential.as_response()}


@router.get("/identity-issuer")
async def get_identity_issuer():
    """Dirección pública del emisor, para que el cliente la fije y compare.

    Devuelve `configured: false` en vez de una dirección inventada cuando el
    emisor no tiene llave: el cliente debe poder distinguir "no configurado"
    de "configurado con otra llave".
    """
    if not settings.IDENTITY_ISSUER_PRIVATE_KEY.strip():
        return {"configured": False, "issuer_address": None}
    try:
        return {"configured": True, "issuer_address": identity_issuer.issuer_address()}
    except identity_issuer.IdentityIssuanceError:
        return {"configured": False, "issuer_address": None}

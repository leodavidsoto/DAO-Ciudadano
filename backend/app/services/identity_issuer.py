"""
Emisión de credenciales de identidad ZK (ADR-001, D-2).

Flujo completo, en el orden en que importa:

  1. La sesión SIWE debe pertenecer exactamente a `wallet_address` (lo aplica
     el router: sin esto, alguien podría pedir una credencial ligada a la
     wallet de otra persona).
  2. Se canjea el grant civil de un solo uso -> `subject_key`.
  3. Se comprueba que `membership_scope` coincide con `membershipScope()`
     del contrato configurado. El scope ata la credencial a un despliegue
     concreto; aceptar otro permitiría reutilizar la prueba en otra red.
  4. Se inserta el commitment (una hoja por sujeto) y se obtiene la ruta.
  5. Se aprueba la raíz on-chain ANTES de responder. Si se respondiera antes,
     el ciudadano tendría una credencial que el contrato rechaza.
  6. Se firma la credencial con EIP-191.

Lo que el backend NUNCA recibe ni guarda: `identitySecret`, la firma de vuelta,
la ruta al mintear, ni dato civil alguno. El `subject_key` es un identificador
ciego que aporta el proveedor.

El mensaje firmado es un contrato literal con el frontend
(`REQUEST_TO_CLAUDE.md`). Cualquier cambio —incluido el orden de las líneas o
las mayúsculas de la dirección— invalida todas las credenciales emitidas.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ..core.config import settings
from . import identity_grant, identity_tree

logger = logging.getLogger(__name__)

CREDENTIAL_DOMAIN = "DAO Ciudadana Identity Credential v1"


class IdentityIssuanceError(RuntimeError):
    """La credencial no se pudo emitir."""


@dataclass(frozen=True)
class IssuedCredential:
    signature: str
    identity_root: int
    identity_commitment: int
    membership_scope: int
    wallet_address: str
    path_elements: list[int]
    path_indices: list[int]

    def as_response(self) -> dict:
        return {
            "signature": self.signature,
            "identity_root": str(self.identity_root),
            "identity_commitment": str(self.identity_commitment),
            "membership_scope": str(self.membership_scope),
            "wallet_address": self.wallet_address,
            "path_elements": [str(v) for v in self.path_elements],
            "path_indices": [str(v) for v in self.path_indices],
        }


def credential_message(
    wallet_address: str,
    identity_root: int,
    membership_scope: int,
    identity_commitment: int,
) -> str:
    """Mensaje EIP-191 exacto acordado con el frontend.

    Dirección en minúsculas y enteros decimales canónicos. El cliente
    reconstruye esta misma cadena para recuperar el firmante: si difiere en un
    solo carácter, la verificación falla y la credencial se descarta.
    """
    return (
        f"{CREDENTIAL_DOMAIN}\n"
        f"recipient:{wallet_address.lower()}\n"
        f"identityRoot:{identity_root}\n"
        f"scope:{membership_scope}\n"
        f"commitment:{identity_commitment}"
    )


def issuer_address() -> str:
    """Dirección del emisor, para publicarla y que el cliente la fije."""
    from eth_account import Account

    key = settings.IDENTITY_ISSUER_PRIVATE_KEY.strip()
    if not key:
        raise IdentityIssuanceError("IDENTITY_ISSUER_PRIVATE_KEY no está configurada.")
    return Account.from_key(key).address


def sign_credential(message: str) -> str:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    key = settings.IDENTITY_ISSUER_PRIVATE_KEY.strip()
    if not key:
        raise IdentityIssuanceError("IDENTITY_ISSUER_PRIVATE_KEY no está configurada.")
    signed = Account.from_key(key).sign_message(encode_defunct(text=message))
    return signed.signature.hex()


def _normalized_signature(signature: str) -> str:
    return signature if signature.startswith("0x") else f"0x{signature}"


async def issue_credential(
    wallet_address: str,
    identity_commitment: int,
    membership_scope: int,
    grant: str,
    browser_binding: Optional[str] = None,
) -> IssuedCredential:
    """Emite la credencial completa. Ver el orden de pasos en el docstring."""
    if not settings.IDENTITY_ISSUER_PRIVATE_KEY.strip():
        raise IdentityIssuanceError(
            "El emisor de credenciales no está configurado (IDENTITY_ISSUER_PRIVATE_KEY)."
        )

    # 1. Scope: debe coincidir con el del contrato desplegado.
    await _assert_scope_matches_contract(membership_scope)

    # 2. Grant civil de un solo uso. Si ya se canjeó, puede ser un reintento
    #    legítimo: se recupera el sujeto y la ruta ya emitida.
    subject_key: Optional[str]
    try:
        subject_key = await identity_grant.consume(
            grant, browser_binding=browser_binding
        )
    except identity_grant.IdentityGrantError:
        subject_key = await identity_grant.peek_subject(grant)
        if not subject_key:
            raise
        existing = await identity_tree.find_by_subject(subject_key)
        if existing is None:
            # El grant se gastó pero la hoja nunca llegó a escribirse: no hay
            # forma segura de continuar sin arriesgar una segunda identidad.
            raise IdentityIssuanceError(
                "El grant ya fue usado pero no hay credencial asociada. "
                "Solicita una verificación civil nueva."
            )
        # El grant se consumió en un intento anterior. Si aquella aprobación
        # de raíz falló, la credencial existente no serviría para mintear, así
        # que se vuelve a aprobar/verificar antes de devolverla.
        await _approve_root_onchain(existing.root)
        return _build_credential(
            wallet_address, existing, identity_commitment, membership_scope
        )

    # 3. Inserción idempotente por sujeto.
    try:
        witness = await identity_tree.insert_commitment(
            identity_commitment, subject_key
        )
    except identity_tree.IdentityTreeError as exc:
        raise IdentityIssuanceError(str(exc)) from exc

    # 4. Aprobar la raíz on-chain ANTES de responder.
    await _approve_root_onchain(witness.root)

    return _build_credential(
        wallet_address, witness, identity_commitment, membership_scope
    )


def _build_credential(
    wallet_address: str,
    witness: identity_tree.MerkleWitness,
    identity_commitment: int,
    membership_scope: int,
) -> IssuedCredential:
    message = credential_message(
        wallet_address, witness.root, membership_scope, identity_commitment
    )
    signature = _normalized_signature(sign_credential(message))
    return IssuedCredential(
        signature=signature,
        identity_root=witness.root,
        identity_commitment=identity_commitment,
        membership_scope=membership_scope,
        wallet_address=wallet_address,
        path_elements=witness.path_elements,
        path_indices=witness.path_indices,
    )


async def _assert_scope_matches_contract(membership_scope: int) -> None:
    """El scope declarado debe ser el `membershipScope()` del contrato.

    Se consulta la cadena, no la configuración: el scope se deriva de
    version + chainId + address(this) dentro del propio contrato, así que es
    la cadena la única fuente de verdad.
    """
    import asyncio

    from . import chain_service

    onchain_scope = await asyncio.to_thread(chain_service.membership_scope)
    if onchain_scope is None:
        raise IdentityIssuanceError(
            "No se pudo leer membershipScope() del contrato; no se emite una "
            "credencial que quizá no sea válida."
        )
    if onchain_scope != membership_scope:
        raise IdentityIssuanceError(
            "El scope de membresía no corresponde al contrato configurado."
        )


async def _approve_root_onchain(identity_root: int) -> None:
    import asyncio

    from . import chain_service

    try:
        await asyncio.to_thread(chain_service.approve_identity_root, identity_root)
    except chain_service.ChainMintError as exc:
        raise IdentityIssuanceError(
            "No se pudo aprobar la raíz de identidad on-chain; la credencial "
            "no serviría para mintear."
        ) from exc

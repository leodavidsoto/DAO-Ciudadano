"""
Reconciliación de `members` con un SBT ya emitido on-chain.

Vive en `services/` porque ahora hay DOS caminos que emiten credenciales y
ambos deben dejar exactamente el mismo registro:

* `/membership/mint-zk` — el relayer EOA envía la prueba y paga el gas,
* `/erc4337/submit-mint` — el ciudadano firma una SafeOp y un Paymaster paga.

Tenerlo duplicado en cada router era el camino corto a que uno de los dos se
quedara atrás. De hecho el de ERC-4337 nunca llegó a escribir en `members`:
la persona obtenía su SBT on-chain y quedaba fuera de la gobernanza, porque
el gate de membresía consulta MongoDB (MEMBERSHIP_SOURCE=mongo).
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from ..core.database import members_collection
from .membership_verifier import invalidate_cached_membership


async def reconcile_onchain_membership(
    wallet_address: str,
    token_id: Optional[int],
    tx_hash: Optional[str],
    nullifier_hash: Optional[str] = None,
) -> None:
    """Refleja en `members` un SBT emitido por la vía ZK.

    `identity_verified` va en True porque la prueba ZK ES la verificación: el
    contrato solo acepta raíces que el emisor aprobó tras consumir un grant
    civil de un solo uso. Es el único camino que puede ponerlo en True — el
    minteo demo nunca lo hace.

    Idempotente: es un upsert por `wallet_address`, así que reejecutarlo tras
    una caída no duplica la membresía ni pierde el `created_at` original.

    La invalidación de la caché va aquí dentro y no en cada llamador: con
    MEMBERSHIP_SOURCE=onchain, un "no es miembro" cacheado segundos antes
    dejaría a quien acaba de recibir su credencial sin poder votar durante el
    resto del TTL.
    """
    normalized = wallet_address.lower()
    now = datetime.now(timezone.utc)

    await members_collection().update_one(
        {"wallet_address": normalized},
        {
            "$set": {
                "wallet_address": normalized,
                "token_id": token_id,
                "tx_hash": tx_hash,
                "nullifier_hash": nullifier_hash,
                "status": "active",
                "issuance_mode": "onchain",
                "identity_verified": True,
                # No hay doc_hash: el documento nunca llegó al servidor.
                "assurance_level": "ZK_VERIFIED",
                "updated_at": now,
            },
            "$setOnInsert": {
                "id": str(uuid.uuid4()),
                "created_at": now,
            },
        },
        upsert=True,
    )

    invalidate_cached_membership(normalized)

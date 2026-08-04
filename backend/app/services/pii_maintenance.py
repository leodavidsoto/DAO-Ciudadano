"""
Lógica de mantenimiento de la PII cifrada (ROADMAP 1.3 / 1.4).

Vive en `services/` y no dentro del script por la misma razón que el resto de
la lógica de negocio: para poder ejecutarla en los tests. Una herramienta que
reescribe datos personales de ciudadanos y que nadie ha ejecutado nunca en un
test es exactamente lo que este repositorio no permite —y el momento de
descubrir que rota mal es antes de tocar la base de producción, no durante.

`scripts/pii_maintenance.py` es solo la interfaz de línea de comandos.

Todas las funciones aceptan `apply=False` y en ese modo NO escriben nada:
devuelven lo que harían. El script hereda ese comportamiento por defecto.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from ..core import retention
from ..core.crypto import decrypt, encrypt, is_current, rotate
from ..core.database import get_collection
from ..core.identity import lookup_key

# Inventario de campos cifrados por colección (lo que 1.4 pedía documentar).
# Si algún día se cifra otro campo, se añade aquí y la rotación lo cubre.
ENCRYPTED_FIELDS: Dict[str, tuple] = {
    "users": ("rut", "email", "nombre", "apellido"),
}

# Índices ciegos y el campo cifrado del que se derivan: (clave, origen, dominio).
LOOKUP_FIELDS: Dict[str, tuple] = {
    "users": (("rut_key", "rut", "rut"), ("email_key", "email", "email")),
}

# Prefijo de un token Fernet. Permite distinguir PII legacy en texto plano de
# PII ya cifrada sin intentar descifrar campo por campo.
_FERNET_PREFIX = "gAAAAA"


def looks_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_FERNET_PREFIX)


@dataclass
class MaintenanceReport:
    scanned: int = 0
    changed: int = 0
    failures: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


async def scan(collection: str) -> dict:
    """Cuántos documentos están pendientes y por qué motivo.

    Los tres motivos son distintos y se cuentan por separado: "cifrado con
    llave antigua" se arregla rotando, "texto plano" es una migración legacy y
    "índice desfasado" es una rotación de pepper a medias.
    """
    fields = ENCRYPTED_FIELDS.get(collection, ())
    lookups = LOOKUP_FIELDS.get(collection, ())
    result = {
        "total": 0,
        "stale_cipher": 0,
        "plaintext": 0,
        "stale_lookup": 0,
        "undecryptable": 0,
    }

    async for doc in get_collection(collection).find({}):
        result["total"] += 1
        for name in fields:
            value = doc.get(name)
            if value is None:
                continue
            if not looks_encrypted(value):
                result["plaintext"] += 1
                break
            if not is_current(value):
                result["stale_cipher"] += 1
                break

        for key_field, source_field, domain in lookups:
            source = doc.get(source_field)
            if source is None or not doc.get(key_field):
                continue
            try:
                plaintext = decrypt(source) if looks_encrypted(source) else source
            except ValueError:
                result["undecryptable"] += 1
                break
            if doc[key_field] != lookup_key(plaintext, domain):
                result["stale_lookup"] += 1
                break

    return result


async def rotate_encrypted_fields(
    collection: str, apply: bool = False
) -> MaintenanceReport:
    """Re-cifra con la llave primaria y cifra la PII legacy que esté en claro.

    Nunca escribe un valor en texto plano: `rotate()` descifra y vuelve a
    cifrar en una sola operación, y el texto plano legacy se cifra al vuelo.
    """
    report = MaintenanceReport()
    fields = ENCRYPTED_FIELDS.get(collection, ())

    async for doc in get_collection(collection).find({}):
        report.scanned += 1
        updates = {}
        for name in fields:
            value = doc.get(name)
            if value is None:
                continue
            if not looks_encrypted(value):
                # PII legacy en claro: es la migración de 1.4.
                updates[name] = encrypt(value)
                continue
            if is_current(value):
                continue
            try:
                updates[name] = rotate(value)
            except ValueError:
                report.failures.append(
                    f"{collection}/{doc.get('id')}: el campo '{name}' no lo descifra "
                    "ninguna llave configurada; se deja intacto."
                )

        if not updates:
            continue
        report.changed += 1
        if apply:
            updates["updated_at"] = datetime.now(timezone.utc)
            await get_collection(collection).update_one(
                {"_id": doc["_id"]}, {"$set": updates}
            )

    return report


async def reindex_lookup_keys(
    collection: str, apply: bool = False
) -> MaintenanceReport:
    """Recalcula los índices ciegos con el pepper VIGENTE.

    Es lo que cierra una rotación de pepper: mientras queden documentos
    indexados con el anterior, `IDENTITY_PEPPER_PREVIOUS` no se puede retirar
    sin dejar gente fuera.
    """
    report = MaintenanceReport()
    lookups = LOOKUP_FIELDS.get(collection, ())

    async for doc in get_collection(collection).find({}):
        report.scanned += 1
        updates = {}
        for key_field, source_field, domain in lookups:
            source = doc.get(source_field)
            if source is None:
                continue
            try:
                plaintext = decrypt(source) if looks_encrypted(source) else source
            except ValueError:
                report.failures.append(
                    f"{collection}/{doc.get('id')}: no se pudo descifrar "
                    f"'{source_field}'; su índice ciego queda como está."
                )
                continue
            expected = lookup_key(plaintext, domain)
            if doc.get(key_field) != expected:
                updates[key_field] = expected

        if not updates:
            continue
        report.changed += 1
        if apply:
            updates["updated_at"] = datetime.now(timezone.utc)
            await get_collection(collection).update_one(
                {"_id": doc["_id"]}, {"$set": updates}
            )

    return report


async def purge_candidates() -> Dict[str, int]:
    """Documentos que superan una regla de retención MANUAL."""
    counts: Dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for rule in retention.manual_rules():
        cutoff = now - timedelta(seconds=rule.ttl_seconds)
        counts[rule.collection] = await get_collection(rule.collection).count_documents(
            {rule.field: {"$lt": cutoff}}
        )
    return counts


async def purge(apply: bool = False) -> Dict[str, int]:
    """Aplica las reglas de retención manuales. Irreversible con apply=True.

    Las automáticas ya las ejecuta MongoDB con un índice TTL; aquí solo entra
    lo que exige una decisión humana, como el borrado de registros civiles.
    """
    deleted: Dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for rule in retention.manual_rules():
        cutoff = now - timedelta(seconds=rule.ttl_seconds)
        query = {rule.field: {"$lt": cutoff}}
        count = await get_collection(rule.collection).count_documents(query)
        if apply and count:
            result = await get_collection(rule.collection).delete_many(query)
            deleted[rule.collection] = result.deleted_count
        else:
            deleted[rule.collection] = count
    return deleted

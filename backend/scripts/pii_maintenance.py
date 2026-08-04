#!/usr/bin/env python3
"""
Mantenimiento de la PII cifrada: estado, rotación, reindexado y purga.
ROADMAP 1.3 (rotación de llaves) y 1.4 (retención y migración).

TODO SE EJECUTA EN SECO POR DEFECTO. Ningún subcomando escribe en la base sin
`--apply`. Es deliberado: estas operaciones tocan datos personales de
ciudadanos y la purga no se puede deshacer.

La lógica vive en `app/services/pii_maintenance.py` para poder probarla; esto
es solo la interfaz de línea de comandos.

Uso:

    python scripts/pii_maintenance.py status
    python scripts/pii_maintenance.py rotate-pii [--apply]
    python scripts/pii_maintenance.py reindex-lookups [--apply]
    python scripts/pii_maintenance.py purge [--apply]

Antes de `--apply` en producción: haz un snapshot de la base. Es la única
forma de volver atrás si algo falla a mitad de una migración.

── Cómo se rota la llave de cifrado (1.3) ──────────────────────────────────

 1. Genera una llave nueva:
        python -c "from app.core.crypto import generate_key; print(generate_key())"
 2. Publícala DELANTE de la actual, sin quitar la vieja:
        PII_ENCRYPTION_KEYS=<nueva>,<actual>
    Desde ese momento se cifra con la nueva y se sigue descifrando lo viejo.
    Sin downtime y sin parar nada.
 3. python scripts/pii_maintenance.py rotate-pii --apply
 4. Cuando `status` reporte 0 pendientes, quita la vieja de la variable.

Si te saltas el paso 2 y reemplazas la llave directamente, TODA la PII
existente queda ilegible: Fernet no descifra lo que cifró otra llave.

── Cómo se rota el pepper (1.3) ────────────────────────────────────────────

El pepper es más delicado que la llave: los índices ciegos (`rut_key`,
`email_key`) son derivaciones determinísticas suyas, así que cambiarlo
invalida las búsquedas de golpe y nadie puede iniciar sesión.

 1. IDENTITY_PEPPER=<nuevo> y IDENTITY_PEPPER_PREVIOUS=<viejo>
    Las consultas prueban con ambos mientras dure la migración.
 2. python scripts/pii_maintenance.py reindex-lookups --apply
 3. Cuando `status` reporte 0 pendientes, retira IDENTITY_PEPPER_PREVIOUS.

Advertencia honesta: reindexar descifra el RUT y el email de cada usuario en
memoria para recalcular su clave. Ejecútalo en un entorno controlado y no
redirijas su salida a un archivo compartido.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo.errors import PyMongoError  # noqa: E402

from app.core import retention  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.crypto import EncryptionKeyMissing, key_status  # noqa: E402
from app.core.identity import IdentityPepperMissing  # noqa: E402
from app.core.database import Database  # noqa: E402
from app.services import pii_maintenance as service  # noqa: E402


def _connect() -> str:
    mongo_url = os.environ.get("MONGO_URL", settings.MONGO_URL)
    db_name = os.environ.get("DB_NAME", settings.DB_NAME)
    Database.connect(mongo_url, db_name)
    return db_name


async def cmd_status(_args) -> int:
    db_name = _connect()
    keys = key_status()

    print(f"Base de datos: {db_name}")
    print("\n== Llaves de cifrado (PII) ==")
    print(
        f"  configuradas : {keys['configured']} "
        f"(usables {keys['usable']}, inválidas {keys['invalid']})"
    )
    print(f"  primaria     : {keys['primary']}")
    if keys["secondary"]:
        print(f"  secundarias  : {', '.join(keys['secondary'])}  <- solo descifran")
    if keys["rotation_in_progress"]:
        print("  ROTACIÓN EN CURSO: ejecuta `rotate-pii --apply` y luego retira la vieja.")
    if keys["invalid"]:
        print("  ATENCIÓN: hay llaves declaradas que no son Fernet válidas y se ignoran.")

    print("\n== Pepper de índices ciegos ==")
    print(f"  vigente  : {'configurado' if settings.IDENTITY_PEPPER.strip() else 'AUSENTE'}")
    if settings.IDENTITY_PEPPER_PREVIOUS.strip():
        print("  anterior : configurado  <- rotación en curso; retíralo al terminar")

    print("\n== Registros pendientes ==")
    for collection in service.ENCRYPTED_FIELDS:
        counts = await service.scan(collection)
        print(f"  {collection}: {counts['total']} documentos")
        print(f"    - cifrados con llave antigua : {counts['stale_cipher']}")
        print(f"    - en texto plano (legacy)    : {counts['plaintext']}")
        print(f"    - índices ciegos desfasados  : {counts['stale_lookup']}")
        if counts["undecryptable"]:
            print(
                f"    - ILEGIBLES                  : {counts['undecryptable']}"
                "  <- falta la llave que los cifró"
            )

    print("\n== Retención ==")
    for rule in retention.describe():
        window = (
            "indefinida" if rule["retention_days"] is None
            else f"{rule['retention_days']} días"
        )
        print(f"  {rule['collection']}.{rule['field']}: {window} ({rule['enforced']})")
    for collection, count in (await service.purge_candidates()).items():
        print(f"  pendientes de purga manual en {collection}: {count}")

    Database.close()
    return 0


async def _run_reports(runner, args, verb_applied: str, verb_dry: str) -> int:
    _connect()
    failed = 0
    for collection in service.ENCRYPTED_FIELDS:
        report = await runner(collection, apply=args.apply)
        verb = verb_applied if args.apply else verb_dry
        print(f"{collection}: {verb} {report.changed} de {report.scanned} documentos.")
        for failure in report.failures:
            print(f"  ! {failure}")
        failed += len(report.failures)

    if not args.apply:
        print("Ejecución en seco. Repite con --apply para escribir.")
    Database.close()
    return 1 if failed else 0


async def cmd_rotate_pii(args) -> int:
    return await _run_reports(
        service.rotate_encrypted_fields, args, "re-cifrados", "se re-cifrarían"
    )


async def cmd_reindex_lookups(args) -> int:
    return await _run_reports(
        service.reindex_lookup_keys, args, "reindexados", "se reindexarían"
    )


async def cmd_purge(args) -> int:
    _connect()
    manual = retention.manual_rules()
    if not manual:
        print(
            "No hay ninguna regla de purga manual activa. El borrado de registros "
            "de ciudadanos está desactivado (INACTIVE_USER_RETENTION_DAYS=0), que "
            "es el valor por defecto y una decisión deliberada."
        )
        Database.close()
        return 0

    for rule in manual:
        print(f"{rule.collection}.{rule.field}: retención de {rule.ttl_seconds} s")
        print(f"  motivo de la regla: {rule.reason}")

    results = await service.purge(apply=args.apply)
    for collection, count in results.items():
        if args.apply:
            print(f"  {collection}: BORRADOS {count} documentos (irreversible).")
        else:
            print(f"  {collection}: se borrarían {count} documentos.")

    if not args.apply:
        print("Ejecución en seco. Repite con --apply para borrar.")
    Database.close()
    return 0


COMMANDS = {
    "status": cmd_status,
    "rotate-pii": cmd_rotate_pii,
    "reindex-lookups": cmd_reindex_lookups,
    "purge": cmd_purge,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Escribe los cambios. Sin esto, solo informa.",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(COMMANDS[args.command](args))
    except PyMongoError as exc:
        # Un traceback de pymongo no le dice a un operador qué arreglar, y
        # esta herramienta se ejecuta con prisa y sobre datos personales.
        print(
            "\nNo se pudo hablar con MongoDB. Revisa MONGO_URL y que la base "
            f"esté accesible desde esta máquina.\n  detalle: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    except (EncryptionKeyMissing, IdentityPepperMissing) as exc:
        print(f"\nConfiguración incompleta: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

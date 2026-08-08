import argparse
import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.core import database
from app.services import pii_maintenance

logger = logging.getLogger("scripts.pii_maintenance")


async def init_db():
    database.Database.connect(settings.MONGO_URL, settings.DB_NAME)
    await database.Database.ensure_indexes()


async def run_status(args):
    await init_db()
    for collection in pii_maintenance.ENCRYPTED_FIELDS.keys():
        print(f"\nColección: {collection}")
        res = await pii_maintenance.scan(collection)
        print(f"Total registros: {res['total']}")
        print(f"Textos planos (legacy): {res['plaintext']}")
        print(f"Cifrado desactualizado: {res['stale_cipher']}")
        print(f"Índices ciegos desfasados: {res['stale_lookup']}")
        print(f"Registros indescifrables: {res['undecryptable']}")


async def run_rotate(args):
    await init_db()
    for collection in pii_maintenance.ENCRYPTED_FIELDS.keys():
        print(f"\nRotando campos cifrados en: {collection} (apply={args.apply})")
        report = await pii_maintenance.rotate_encrypted_fields(
            collection, apply=args.apply
        )
        print(f"Escaneados: {report.scanned}, Cambiados: {report.changed}")
        if report.failures:
            print("Fallos detectados:")
            for f in report.failures:
                print(f"  - {f}")


async def run_reindex(args):
    await init_db()
    for collection in pii_maintenance.ENCRYPTED_FIELDS.keys():
        print(f"\nReindexando llaves ciegas en: {collection} (apply={args.apply})")
        report = await pii_maintenance.reindex_lookup_keys(collection, apply=args.apply)
        print(f"Escaneados: {report.scanned}, Cambiados: {report.changed}")
        if report.failures:
            print("Fallos detectados:")
            for f in report.failures:
                print(f"  - {f}")


async def run_purge(args):
    await init_db()
    print(f"\nPurgando registros vencidos (apply={args.apply})")
    if not args.apply:
        counts = await pii_maintenance.purge_candidates()
        for coll, count in counts.items():
            print(f"  - {coll}: {count} listos para eliminar")
    else:
        deleted = await pii_maintenance.purge(apply=True)
        for coll, count in deleted.items():
            print(f"  - {coll}: {count} eliminados")


def main():
    parser = argparse.ArgumentParser(
        description="Mantenimiento de PII (Cifrado y Retención)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Muestra el estado de la PII")
    status_parser.set_defaults(func=run_status)

    rotate_parser = subparsers.add_parser("rotate-pii", help="Rota/Migra la PII")
    rotate_parser.add_argument(
        "--apply", action="store_true", help="Aplica los cambios en base de datos"
    )
    rotate_parser.set_defaults(func=run_rotate)

    reindex_parser = subparsers.add_parser(
        "reindex-pii", help="Reindexa llaves ciegas con el pepper vigente"
    )
    reindex_parser.add_argument(
        "--apply", action="store_true", help="Aplica los cambios en base de datos"
    )
    reindex_parser.set_defaults(func=run_reindex)

    purge_parser = subparsers.add_parser(
        "purge-pii", help="Aplica retención manual (eliminar)"
    )
    purge_parser.add_argument(
        "--apply", action="store_true", help="Elimina registros irremediablemente"
    )
    purge_parser.set_defaults(func=run_purge)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()

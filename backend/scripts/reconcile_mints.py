"""
Reconcilia las operaciones de minteo abiertas contra la cadena.

Para qué sirve: entre difundir la transacción y saber cómo acabó hay hasta
120 s de espera de recibo. Si el proceso muere ahí, la operación queda abierta
en Mongo mientras la cadena ya decidió. Esto la cierra con lo que dice la
cadena, nunca con una suposición.

    python scripts/reconcile_mints.py status
    python scripts/reconcile_mints.py sweep --limit 100

`sweep` escribe: confirma las que tienen SBT (y las refleja en `members`),
marca `failed` las que no llegaron a la cadena —para que el ciudadano pueda
reintentar— y deja en `needs_review` las que se contradicen. Las que siguen
realmente en vuelo no se tocan.

No hay barrido automático en segundo plano a propósito: con varias instancias,
cada una correría el suyo y multiplicaría las llamadas al RPC sin coordinación.
"""

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import database  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import mint_operations  # noqa: E402

logger = logging.getLogger("scripts.reconcile_mints")


async def init_db():
    database.Database.connect(settings.MONGO_URL, settings.DB_NAME)
    await database.Database.ensure_indexes()


async def run_status(_args):
    await init_db()
    collection = mint_operations.mint_operations_collection()
    print("Operaciones de minteo por estado:")
    for state in (
        mint_operations.PENDING,
        mint_operations.SUBMITTED,
        mint_operations.CONFIRMED,
        mint_operations.FAILED,
        mint_operations.NEEDS_REVIEW,
    ):
        print(f"  {state:<13} {await collection.count_documents({'status': state})}")

    flagged = collection.find({"status": mint_operations.NEEDS_REVIEW})
    async for operation in flagged:
        print(
            f"\n  REVISAR {operation['nullifier_hash']}: "
            f"{operation.get('review_reason', 'sin motivo registrado')}"
        )


async def run_sweep(args):
    await init_db()
    summary = await mint_operations.sweep(limit=args.limit)
    print(f"Operaciones revisadas: {summary['scanned']}")
    print(f"  confirmadas:   {summary[mint_operations.CONFIRMED]}")
    print(f"  fallidas:      {summary[mint_operations.FAILED]}")
    print(f"  a revisar:     {summary[mint_operations.NEEDS_REVIEW]}")
    print(f"  aún en vuelo:  {summary[mint_operations.IN_FLIGHT]}")


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Recuento por estado y operaciones a revisar")

    sweep = sub.add_parser("sweep", help="Reconciliar operaciones abiertas")
    sweep.add_argument("--limit", type=int, default=100)

    args = parser.parse_args()
    handlers = {"status": run_status, "sweep": run_sweep}
    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main()

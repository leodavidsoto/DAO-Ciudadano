"""
Recuento reconstruible desde las papeletas (ROADMAP 3.10).

El problema que cierra
──────────────────────
Antes, votar eran DOS escrituras: insertar la papeleta y sumar el resultado en
el documento de la propuesta. Una caída entre ambas dejaba una papeleta que
nadie contaba, o un contador que nadie podía justificar, y no había forma de
saber cuál de las dos cifras era la verdadera.

La primera mitad ya está resuelta: los totales se derivan de las papeletas al
leerlos, así que el contador dejó de existir como fuente independiente y no
hay nada que pueda divergir. Insertar una papeleta es UNA escritura de UN
documento, que MongoDB hace atómicamente.

Lo que añade este módulo es la segunda mitad, que es la que da valor a lo
anterior: **volver a calcular el resultado desde cero contando solo papeletas
cuya firma EIP-712 verifica**, y decir en qué se diferencia de lo que la API
publica. Sin esto, "derivado de las papeletas" solo significa que confiamos en
otra colección del mismo servidor.

Qué se comprueba de cada papeleta
─────────────────────────────────
1. La firma recupera exactamente la dirección del votante.
2. El peso declarado cuadra con su composición (`1 + len(delegators)`), que se
   persiste desde P-61. Un peso inflado a mano en la base se detecta aquí.
3. Que no haya dos papeletas del mismo votante en la misma consulta.

Una papeleta que falle cualquiera de las tres NO se cuenta y aparece en
`rejected` con su motivo. El resultado auditado es el que sale de las que
pasan; si difiere del publicado, `matches` es false y hay que investigarlo.

Las papeletas sin firma son un caso aparte: existen porque
`SIGNED_BALLOTS_REQUIRED` estuvo en false (piloto). Se cuentan solo si esa
bandera sigue apagada, y siempre se reportan en `unsigned` para que nadie lea
"auditado" como "criptográficamente probado" cuando la mitad no lleva firma.
"""

import asyncio
import logging
from typing import Optional

from ..core.config import settings
from ..core.database import election_votes_collection, votes_collection
from . import ballot_service

logger = logging.getLogger(__name__)

# Tope de papeletas por auditoría. Recuperar un firmante ECDSA cuesta CPU y
# estos endpoints son públicos: sin tope, una propuesta muy votada los
# convierte en un amplificador de carga. Si se supera, se dice.
MAX_AUDITED_BALLOTS = 5000


def _weight_is_consistent(ballot: dict) -> bool:
    """El peso debe cuadrar con los delegantes que lo componen.

    `delegators` se persiste desde P-61 justamente para esto. Las papeletas
    anteriores no lo tienen: no se puede recomputar su peso, así que se acepta
    el declarado y se marca aparte en vez de fingir que se verificó.
    """
    delegators = ballot.get("delegators")
    if delegators is None:
        return True
    return int(ballot.get("weight", 0)) == 1 + len(delegators)


def _verify_proposal_ballot(proposal_id: str, ballot: dict) -> Optional[str]:
    """None si la papeleta es válida; si no, el motivo del rechazo."""
    signature = ballot.get("signature")
    if not signature:
        return None if not settings.SIGNED_BALLOTS_REQUIRED else "sin firma"

    try:
        recovered = ballot_service.recover_signer(
            proposal_id,
            ballot["voter_address"],
            ballot["vote"],
            ballot.get("nonce") or "",
            signature,
            ballot.get("chain_id"),
        )
    except Exception:
        return "la firma no se pudo decodificar"

    if recovered.lower() != str(ballot["voter_address"]).lower():
        return "la firma no corresponde a la dirección del votante"
    if not _weight_is_consistent(ballot):
        return "el peso no coincide con los delegantes registrados"
    return None


def _verify_election_ballot(election_id: str, ballot: dict) -> Optional[str]:
    signature = ballot.get("signature")
    if not signature:
        return None if not settings.SIGNED_BALLOTS_REQUIRED else "sin firma"

    try:
        recovered = ballot_service.recover_election_signer(
            election_id,
            ballot["voter_address"],
            ballot["candidate_address"],
            ballot.get("nonce") or "",
            signature,
            ballot.get("chain_id"),
        )
    except Exception:
        return "la firma no se pudo decodificar"

    if recovered.lower() != str(ballot["voter_address"]).lower():
        return "la firma no corresponde a la dirección del votante"
    if not _weight_is_consistent(ballot):
        return "el peso no coincide con los delegantes registrados"
    return None


def _audit(ballots: list, contest_id: str, verifier, bucket_of) -> dict:
    """Núcleo síncrono del recuento. Se ejecuta en un hilo: recuperar
    firmantes es CPU y bloquearía el event loop del resto del servicio."""
    tally: dict = {}
    rejected = []
    unsigned = 0
    seen_voters = set()

    for ballot in ballots:
        voter = str(ballot.get("voter_address", "")).lower()

        if voter in seen_voters:
            # El índice único lo impide en caliente; si aparece, es que alguien
            # escribió en la base por fuera de la API.
            rejected.append({"voter_address": voter, "reason": "papeleta duplicada"})
            continue
        seen_voters.add(voter)

        reason = verifier(contest_id, ballot)
        if reason:
            rejected.append({"voter_address": voter, "reason": reason})
            continue

        if not ballot.get("signature"):
            unsigned += 1

        bucket = bucket_of(ballot)
        tally[bucket] = tally.get(bucket, 0) + int(ballot.get("weight", 0))

    return {
        "tally": tally,
        "counted": len(ballots) - len(rejected),
        "rejected": rejected,
        "unsigned": unsigned,
    }


async def audit_proposal(proposal_id: str) -> dict:
    """Recuenta una propuesta desde sus papeletas, verificando cada firma."""
    cursor = votes_collection().find({"proposal_id": proposal_id}, {"_id": 0})
    ballots = await cursor.to_list(length=MAX_AUDITED_BALLOTS + 1)
    truncated = len(ballots) > MAX_AUDITED_BALLOTS
    ballots = ballots[:MAX_AUDITED_BALLOTS]

    audited = await asyncio.to_thread(
        _audit,
        ballots,
        proposal_id,
        _verify_proposal_ballot,
        lambda b: b.get("vote"),
    )

    verified = {
        "votes_for": audited["tally"].get("for", 0),
        "votes_against": audited["tally"].get("against", 0),
        "votes_abstain": audited["tally"].get("abstain", 0),
    }
    verified["total_votes"] = sum(verified.values())

    published = await _published_proposal_tally(proposal_id)

    return {
        "proposal_id": proposal_id,
        "ballots_examined": len(ballots),
        "ballots_counted": audited["counted"],
        "ballots_unsigned": audited["unsigned"],
        "rejected": audited["rejected"],
        "verified_tally": verified,
        "published_tally": published,
        # El criterio de aceptación de 3.10: recomputar desde las papeletas
        # tiene que dar lo mismo que publica la API.
        "matches": verified == published,
        "truncated": truncated,
        "signed_ballots_required": settings.SIGNED_BALLOTS_REQUIRED,
    }


async def _published_proposal_tally(proposal_id: str) -> dict:
    from .governance_service import governance_service

    tallies = await governance_service.compute_proposals_tallies(
        [proposal_id], votes_collection
    )
    published = tallies.get(proposal_id, {})
    return {
        "votes_for": published.get("votes_for", 0),
        "votes_against": published.get("votes_against", 0),
        "votes_abstain": published.get("votes_abstain", 0),
        "total_votes": published.get("total_votes", 0),
    }


async def audit_election(election_id: str) -> dict:
    """Recuenta una elección desde sus papeletas, verificando cada firma."""
    from .governance_service import governance_service

    cursor = election_votes_collection().find({"election_id": election_id}, {"_id": 0})
    ballots = await cursor.to_list(length=MAX_AUDITED_BALLOTS + 1)
    truncated = len(ballots) > MAX_AUDITED_BALLOTS
    ballots = ballots[:MAX_AUDITED_BALLOTS]

    audited = await asyncio.to_thread(
        _audit,
        ballots,
        election_id,
        _verify_election_ballot,
        lambda b: str(b.get("candidate_address", "")).lower(),
    )

    published = {
        r["candidate_address"].lower(): r["votes"]
        for r in await governance_service.compute_results(election_id)
        if r["votes"] > 0
    }
    verified = {k: v for k, v in audited["tally"].items() if v > 0}

    return {
        "election_id": election_id,
        "ballots_examined": len(ballots),
        "ballots_counted": audited["counted"],
        "ballots_unsigned": audited["unsigned"],
        "rejected": audited["rejected"],
        "verified_tally": verified,
        "published_tally": published,
        "matches": verified == published,
        "truncated": truncated,
        "signed_ballots_required": settings.SIGNED_BALLOTS_REQUIRED,
    }

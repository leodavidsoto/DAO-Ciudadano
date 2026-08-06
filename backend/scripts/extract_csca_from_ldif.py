#!/usr/bin/env python3
"""
Extrae los CSCA de un país desde el repositorio LDIF de la ICAO PKD.

Contexto (ROADMAP 4.x / 5.8): la Autenticación Pasiva de la cédula chilena
necesita el certificado raíz del Registro Civil como ancla de confianza. La
descarga oficial es `icaopkd-002-complete-NNN.ldif`, que **no** contiene
certificados sueltos en `userCertificate;binary`: contiene *master lists*
(`pkdMasterListContent;binary`), y cada una es un CMS SignedData cuyo
contenido encapsulado es la estructura `CscaMasterList` de ICAO 9303-12:

    CscaMasterList ::= SEQUENCE {
        version    INTEGER (0),
        certList   SET OF Certificate }

Es decir: hay que abrir dos capas de ASN.1 antes de ver un X.509. Cada país
publica su master list *y firma en ella las CSCA de los demás*, así que el
mismo certificado de Chile aparece decenas de veces, emitido por distintos
países. Eso es una ventaja y por eso este script no se queda con la primera
copia: cuenta en cuántas master lists **de emisores distintos** aparece cada
certificado. Un CSCA que sólo aparece en la master list del propio país tiene
menos respaldo que uno corroborado por veinte administraciones.

Deliberadamente NO verifica la firma de las master lists: la única forma de
hacerlo bien sería contra la CSCA del país emisor, que es exactamente lo que
estamos tratando de obtener (dependencia circular). La confianza aquí viene
del canal: el archivo se descarga del PKD de la ICAO. Lo que sí se hace es
exigir corroboración cruzada y reportarla, para que quien apruebe el .pem vea
sobre qué está firmando.

Uso:
    python backend/scripts/extract_csca_from_ldif.py \
        "icao/icaopkd-002-complete-527 (1).ldif" \
        --country CL \
        --out backend/app/certs/csca_chile.pem

    # Ver qué hay antes de escribir nada:
    python backend/scripts/extract_csca_from_ldif.py <ldif> --country CL --dry-run
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

# Atributos LDIF que pueden traer material criptográfico. El PKD usa el
# primero; los otros dos aparecen en volcados de otras fuentes y salen gratis.
MASTER_LIST_ATTRS = {"pkdmasterlistcontent", "cscamasterlistdata"}
CERTIFICATE_ATTRS = {"usercertificate", "cacertificate", "crosscertificatepair"}


# --------------------------------------------------------------------------
# LDIF
# --------------------------------------------------------------------------


def iter_ldif_attributes(path: Path) -> Iterator[tuple[str, str, bytes]]:
    """Rinde `(dn, atributo_normalizado, valor_binario)` por cada `attr::` base64.

    Implementa el desdoblado de líneas de RFC 2849: una línea que empieza con
    UN espacio continúa la anterior, sin ese espacio. El archivo del PKD parte
    los base64 en columnas de 76, así que ignorar esto produce base64 truncado
    y certificados que "no parsean" sin explicación.
    """
    current_dn = ""
    pending: Optional[str] = None

    def flush(line: Optional[str]) -> Optional[tuple[str, str, bytes]]:
        nonlocal current_dn
        if not line or ":" not in line:
            return None
        name, _, raw = line.partition(":")
        if raw.startswith(":"):  # `attr:: <base64>`
            encoded = raw[1:].strip()
            try:
                value = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return None
        else:
            value = raw.strip().encode("utf-8", "replace")

        # `pkdMasterListContent;binary` -> `pkdmasterlistcontent`
        attr = name.strip().lower().split(";")[0]
        if attr == "dn":
            current_dn = value.decode("utf-8", "replace")
            return None
        return (current_dn, attr, value)

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if line.startswith(" "):  # continuación
                if pending is not None:
                    pending += line[1:]
                continue
            emitted = flush(pending)
            if emitted:
                yield emitted
            pending = None if (not line or line.startswith("#")) else line
        emitted = flush(pending)
        if emitted:
            yield emitted


# --------------------------------------------------------------------------
# ASN.1 / CMS — lector DER mínimo
# --------------------------------------------------------------------------
#
# Se hace a mano, sin dependencia nueva, porque lo que hace falta es muy
# acotado: recorrer TLVs para llegar al eContent y devolver los bytes crudos
# de cada Certificate. Los certificados no se interpretan aquí — de eso se
# encarga `cryptography.x509`, que sí es una implementación auditada. Este
# lector nunca decide si algo es válido; sólo delimita dónde empieza y acaba.


class DERError(ValueError):
    """DER mal formado."""


@dataclass(frozen=True)
class TLV:
    tag: int
    constructed: bool
    content: bytes
    raw: bytes


def _read_tlv(data: bytes, offset: int) -> tuple[TLV, int]:
    if offset >= len(data):
        raise DERError("TLV truncado: no hay byte de tag.")
    start = offset
    first = data[offset]
    offset += 1
    tag = first & 0x1F
    if tag == 0x1F:  # tag de forma larga
        tag = 0
        while True:
            if offset >= len(data):
                raise DERError("TLV truncado en un tag de forma larga.")
            byte = data[offset]
            offset += 1
            tag = (tag << 7) | (byte & 0x7F)
            if not byte & 0x80:
                break

    if offset >= len(data):
        raise DERError("TLV truncado: no hay byte de longitud.")
    length_byte = data[offset]
    offset += 1
    if length_byte & 0x80:
        count = length_byte & 0x7F
        if count == 0:
            raise DERError("Longitud indefinida: no es DER válido.")
        if offset + count > len(data):
            raise DERError("TLV truncado en la longitud larga.")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    else:
        length = length_byte

    end = offset + length
    if end > len(data):
        raise DERError("TLV truncado: la longitud excede el buffer.")
    return (
        TLV(
            tag=tag,
            constructed=bool(first & 0x20),
            content=data[offset:end],
            raw=data[start:end],
        ),
        end,
    )


def _children(content: bytes) -> list[TLV]:
    items: list[TLV] = []
    offset = 0
    while offset < len(content):
        item, offset = _read_tlv(content, offset)
        items.append(item)
    return items


def _find_econtent(data: bytes, depth: int = 0) -> Optional[bytes]:
    """Busca el OCTET STRING con el `CscaMasterList` dentro de un CMS.

    Se recorre el árbol en vez de indexar posiciones fijas porque el PKD trae
    master lists de decenas de administraciones distintas, con y sin atributos
    opcionales. Un OCTET STRING vale si su contenido es a su vez un SEQUENCE
    que empieza por INTEGER y sigue por SET — la forma de `CscaMasterList`.
    """
    if depth > 12:
        return None
    try:
        items = _children(data)
    except DERError:
        return None

    for item in items:
        if item.tag == 0x04 and not item.constructed:  # OCTET STRING
            if _looks_like_master_list(item.content):
                return item.content
            nested = _find_econtent(item.content, depth + 1)
            if nested is not None:
                return nested
        elif item.constructed:
            nested = _find_econtent(item.content, depth + 1)
            if nested is not None:
                return nested
    return None


def _looks_like_master_list(data: bytes) -> bool:
    try:
        outer, _ = _read_tlv(data, 0)
    except DERError:
        return False
    if outer.tag != 0x10 or not outer.constructed:  # SEQUENCE
        return False
    try:
        parts = _children(outer.content)
    except DERError:
        return False
    return (
        len(parts) >= 2
        and parts[0].tag == 0x02  # version INTEGER
        and parts[1].tag == 0x11  # certList SET OF
        and parts[1].constructed
    )


def master_list_certificates(content: bytes) -> list[bytes]:
    """Bytes DER de cada Certificate dentro de un `pkdMasterListContent`."""
    econtent = _find_econtent(content)
    if econtent is None:
        return []
    outer, _ = _read_tlv(econtent, 0)
    cert_set = _children(outer.content)[1]
    return [item.raw for item in _children(cert_set.content) if item.tag == 0x10]


# --------------------------------------------------------------------------
# Selección de certificados
# --------------------------------------------------------------------------


@dataclass
class Candidate:
    certificate: x509.Certificate
    der: bytes
    fingerprint: str
    #: DNs de las master lists (una por país emisor) donde aparece.
    corroborated_by: set[str] = field(default_factory=set)

    @property
    def subject(self) -> str:
        return self.certificate.subject.rfc4514_string()

    @property
    def is_self_signed(self) -> bool:
        """Ancla de confianza sí/no, comprobando la firma — no comparando DNs.

        `subject == issuer` es la prueba habitual y aquí sería **incorrecta**.
        Desde la 4ª generación, el Registro Civil rota la clave de la CSCA
        conservando el mismo DN (`CN=CSCA,OU=…,C=CL`), así que el link
        certificate que la generación anterior emite sobre la clave nueva
        tiene subject idéntico a su issuer. Clasificarlo por DN lo ascendería
        a ancla: un eslabón intermedio pasaría a ser raíz, y la cadena
        quedaría anclada en algo que nunca se auto-firmó.

        La definición criptográfica no se deja engañar por eso: es raíz si su
        firma verifica con su propia clave pública.
        """
        try:
            self.certificate.verify_directly_issued_by(self.certificate)
        except Exception:
            return False
        return True

    @property
    def is_ca(self) -> bool:
        try:
            basic = self.certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
        except x509.ExtensionNotFound:
            # ICAO 9303-12 exige BasicConstraints en una CSCA. Sin la
            # extensión no se asume que lo sea.
            return False
        return bool(basic.value.ca)

    def validity(self, now: datetime) -> str:
        start = self.certificate.not_valid_before_utc
        end = self.certificate.not_valid_after_utc
        if now < start:
            return "aún no válido"
        if now > end:
            return "EXPIRADO"
        return "vigente"


def _country_of(certificate: x509.Certificate) -> Optional[str]:
    values = certificate.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
    return values[0].value.strip().upper() if values else None


def collect_candidates(
    ldif: Path, country: str, verbose: bool
) -> tuple[dict[str, Candidate], dict[str, int]]:
    candidates: dict[str, Candidate] = {}
    stats: dict[str, int] = defaultdict(int)

    for dn, attr, value in iter_ldif_attributes(ldif):
        if attr in MASTER_LIST_ATTRS:
            stats["master_lists"] += 1
            try:
                der_certs = master_list_certificates(value)
            except DERError as exc:
                stats["master_lists_ilegibles"] += 1
                if verbose:
                    print(f"  ! master list ilegible en {dn}: {exc}", file=sys.stderr)
                continue
            if not der_certs:
                stats["master_lists_vacias"] += 1
        elif attr in CERTIFICATE_ATTRS:
            der_certs = [value]
        else:
            continue

        for der in der_certs:
            stats["certificados_vistos"] += 1
            try:
                certificate = x509.load_der_x509_certificate(der)
            except Exception:
                stats["certificados_ilegibles"] += 1
                continue
            if _country_of(certificate) != country:
                continue

            fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
            candidate = candidates.get(fingerprint)
            if candidate is None:
                candidate = Candidate(
                    certificate=certificate, der=der, fingerprint=fingerprint
                )
                candidates[fingerprint] = candidate
            candidate.corroborated_by.add(dn)

    return candidates, dict(stats)


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------


def describe(candidate: Candidate, now: datetime) -> str:
    cert = candidate.certificate
    flags = []
    if candidate.is_self_signed:
        flags.append("auto-firmado")
    if candidate.is_ca:
        flags.append("CA")
    flags.append(candidate.validity(now))
    return (
        f"  subject : {candidate.subject}\n"
        f"  issuer  : {cert.issuer.rfc4514_string()}\n"
        f"  validez : {cert.not_valid_before_utc:%Y-%m-%d} -> "
        f"{cert.not_valid_after_utc:%Y-%m-%d}  [{', '.join(flags)}]\n"
        f"  sha256  : {candidate.fingerprint}\n"
        f"  serial  : {cert.serial_number:x}\n"
        f"  corrobo.: {len(candidate.corroborated_by)} master list(s) independientes"
    )


def render_pem(candidates: list[Candidate], source: Path, country: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    roots = sum(1 for c in candidates if c.is_self_signed)
    links = len(candidates) - roots
    header = [
        f"# CSCA trust store — país {country}",
        "#",
        "# GENERADO, NO EDITAR A MANO.",
        f"#   fuente   : {source.name}",
        f"#   sha256   : {digest}",
        f"#   generado : {generated}",
        f"#   script   : backend/scripts/extract_csca_from_ldif.py",
        f"#   contiene : {roots} raíz(ces) auto-firmada(s) + {links} link certificate(s)",
        "#",
        "# Las raíces auto-firmadas son las anclas de confianza. Los link",
        "# certificates NO son anclas: son eslabones que una CSCA emite sobre la",
        "# clave de su sucesora al rotar, y hacen falta para encadenar un DSC",
        "# nuevo cuando el ancla en la que se confía es la generación anterior.",
        "# Quien los carga debe distinguirlos por subject == issuer, no por su",
        "# orden en este archivo.",
        "#",
        "# Cada certificado va precedido de su subject y su huella SHA-256 para",
        "# que la revisión del PR no dependa de decodificar base64 a ojo.",
        "#",
    ]
    blocks = ["\n".join(header)]
    for candidate in candidates:
        cert = candidate.certificate
        role = "ANCLA (raíz auto-firmada)" if candidate.is_self_signed else "link certificate"
        blocks.append(
            "\n".join(
                [
                    f"# rol     : {role}",
                    f"# subject : {candidate.subject}",
                    f"# issuer  : {cert.issuer.rfc4514_string()}",
                    f"# validez : {cert.not_valid_before_utc:%Y-%m-%d} -> "
                    f"{cert.not_valid_after_utc:%Y-%m-%d}",
                    f"# sha256  : {candidate.fingerprint}",
                    f"# corrobo.: {len(candidate.corroborated_by)} master lists",
                ]
            )
            + "\n"
            + cert.public_bytes(Encoding.PEM).decode("ascii").strip()
        )
    return "\n\n".join(blocks) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ldif", type=Path, help="Archivo icaopkd-002-*.ldif")
    parser.add_argument("--country", default="CL", help="Código ISO 3166-1 alfa-2")
    parser.add_argument(
        "--subject-contains",
        action="append",
        default=[],
        help=(
            "Además del país, exige que el subject contenga este texto "
            "(case-insensitive). Repetible: basta con que coincida uno."
        ),
    )
    parser.add_argument("--out", type=Path, help="Ruta del .pem a escribir")
    parser.add_argument(
        "--anchors-dir",
        type=Path,
        help=(
            "Directorio donde escribir UN .pem por ancla auto-firmada (para "
            "assets/csca de la app móvil, que carga un archivo por certificado). "
            "Los link certificates no se escriben aquí: en el móvil serían "
            "anclas, y un eslabón no es una raíz."
        ),
    )
    parser.add_argument(
        "--roots-only",
        action="store_true",
        help="Omite los link certificates; deja sólo raíces auto-firmadas.",
    )
    parser.add_argument(
        "--drop-expired",
        action="store_true",
        help=(
            "Descarta CSCA expiradas. Por defecto se conservan: siguen siendo "
            "la raíz legítima de los documentos emitidos bajo ellas."
        ),
    )
    parser.add_argument(
        "--min-corroboration",
        type=int,
        default=1,
        help=(
            "Master lists independientes mínimas para aceptar un link "
            "certificate. Las raíces no se filtran por esto."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not args.ldif.is_file():
        print(f"No existe el archivo LDIF: {args.ldif}", file=sys.stderr)
        return 2

    country = args.country.strip().upper()
    print(f"Leyendo {args.ldif} (país={country})…", file=sys.stderr)
    candidates, stats = collect_candidates(args.ldif, country, args.verbose)

    print(
        "  master lists: {master_lists}  certificados leídos: {certificados_vistos}".format(
            master_lists=stats.get("master_lists", 0),
            certificados_vistos=stats.get("certificados_vistos", 0),
        ),
        file=sys.stderr,
    )
    for key in ("master_lists_ilegibles", "master_lists_vacias", "certificados_ilegibles"):
        if stats.get(key):
            print(f"  {key}: {stats[key]}", file=sys.stderr)

    now = datetime.now(timezone.utc)
    ordered = sorted(
        candidates.values(),
        key=lambda c: (c.certificate.not_valid_before_utc, c.subject),
    )

    print(f"\n=== {len(ordered)} certificado(s) con C={country} ===\n")
    for candidate in ordered:
        print(describe(candidate, now))
        print()

    # Sólo entran certificados de CA. Un DSC del mismo país también lleva
    # C=CL y colarlo como ancla convertiría a un firmante de documentos en
    # raíz de confianza.
    selected = [c for c in ordered if c.is_ca]

    # Los link certificates se emiten entre generaciones de la MISMA CSCA. Uno
    # cuyo emisor sea de otro país sería un cross-certificate: no aporta a la
    # cadena chilena y ampliaría el conjunto de quien puede firmar una cédula
    # que aceptemos.
    def _issuer_country(certificate: x509.Certificate) -> Optional[str]:
        values = certificate.issuer.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        return values[0].value.strip().upper() if values else None

    foreign_links = [
        c
        for c in selected
        if not c.is_self_signed and _issuer_country(c.certificate) != country
    ]
    selected = [c for c in selected if c not in foreign_links]
    if foreign_links:
        print(
            f"Descartados {len(foreign_links)} cross-certificate(s) emitidos "
            f"fuera de C={country}.",
            file=sys.stderr,
        )

    if args.roots_only:
        selected = [c for c in selected if c.is_self_signed]

    needles = [needle.lower() for needle in args.subject_contains]
    if needles:
        selected = [
            c for c in selected if any(n in c.subject.lower() for n in needles)
        ]

    # Un ancla expirada no se descarta a la ligera: una CSCA caducada sigue
    # siendo la raíz legítima de los DSC que firmó mientras estaba vigente, y
    # de las cédulas que esos DSC firmaron. Se conserva por defecto y es la
    # validez del DSC —no la del ancla— la que decide si el documento sirve.
    if not args.drop_expired:
        pass
    else:
        selected = [c for c in selected if c.validity(now) != "EXPIRADO"]

    selected = [
        c
        for c in selected
        if c.is_self_signed or len(c.corroborated_by) >= args.min_corroboration
    ]

    roots = [c for c in selected if c.is_self_signed]

    print(
        f"=== {len(selected)} seleccionado(s): {len(roots)} ancla(s) + "
        f"{len(selected) - len(roots)} link certificate(s) ==="
    )
    for candidate in selected:
        role = "ancla" if candidate.is_self_signed else "link "
        print(f"  [{role}] {candidate.subject}  [{candidate.fingerprint[:16]}…]")

    if not roots:
        print(
            "\nNingún certificado raíz pasó los filtros. No se escribe un trust "
            "store sin anclas: uno así haría que TODA validación fallara, y un "
            "archivo que existe se confunde con uno que funciona.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run or not (args.out or args.anchors_dir):
        print("\n(dry-run: no se escribió nada)", file=sys.stderr)
        return 0

    if args.anchors_dir:
        args.anchors_dir.mkdir(parents=True, exist_ok=True)
        for index, candidate in enumerate(roots, start=1):
            name = f"csca_{country.lower()}_{index:02d}_{candidate.fingerprint[:16]}.pem"
            (args.anchors_dir / name).write_bytes(
                candidate.certificate.public_bytes(Encoding.PEM)
            )
        print(
            f"\nEscritas {len(roots)} anclas en {args.anchors_dir}", file=sys.stderr
        )

    if not args.out:
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8, no ASCII: los subject del Registro Civil llevan tildes y las
    # cabeceras de este archivo son legibles a propósito. El cuerpo PEM sigue
    # siendo base64 puro, que es lo único que un parser mira.
    args.out.write_text(render_pem(selected, args.ldif, country), encoding="utf-8")
    print(f"\nEscrito: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

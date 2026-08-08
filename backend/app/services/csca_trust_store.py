"""
Trust store de CSCA para la Autenticación Pasiva (ICAO 9303-11, ADR-004).

Carga `backend/app/certs/csca_chile.pem`, generado por
`backend/scripts/extract_csca_from_ldif.py` desde el LDIF del PKD de la ICAO,
y lo separa en dos conjuntos que NO son intercambiables:

* **anclas** — raíces auto-firmadas del Registro Civil. Son el final de toda
  cadena y lo único en lo que se confía por decisión, no por demostración.
* **eslabones** (link certificates) — certificados que una generación de la
  CSCA emite sobre la clave de la siguiente al rotar. Sirven para *construir*
  la ruta, nunca para terminarla.

La distinción se hace verificando la firma, no comparando `subject` con
`issuer`. Desde 2024 el Registro Civil rota la clave de la CSCA conservando el
mismo DN, así que sus link certificates tienen subject idéntico al issuer: por
DN, un eslabón intermedio se clasificaría como raíz y la cadena quedaría
anclada en un certificado que nadie auto-firmó. Con la comprobación de firma
eso no puede pasar.

Falla cerrado en todas sus formas: sin archivo, con archivo ilegible o sin
ninguna ancla utilizable, `load()` lanza. No existe un modo "sin anclas" que
deje pasar documentos — sería exactamente el bypass que la Fase 5.8 elimina.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from ..core.config import settings

logger = logging.getLogger(__name__)

# Ruta por defecto: junto al código, no en un volumen. El trust store es parte
# del artefacto desplegado y debe versionarse con él; leerlo de un directorio
# escribible convertiría "quien pueda escribir ahí" en "quien decida qué
# cédulas son auténticas".
DEFAULT_TRUST_STORE = (
    Path(__file__).resolve().parent.parent / "certs" / "csca_chile.pem"
)


class TrustStoreError(RuntimeError):
    """El trust store no se pudo cargar o no contiene anclas utilizables."""


@dataclass(frozen=True)
class TrustStore:
    #: Raíces auto-firmadas. Terminan una cadena.
    anchors: tuple[x509.Certificate, ...]
    #: Link certificates. Extienden una cadena, nunca la cierran.
    links: tuple[x509.Certificate, ...]
    source: Path

    def __post_init__(self) -> None:
        if not self.anchors:
            raise TrustStoreError(
                f"{self.source} no contiene ninguna CSCA raíz auto-firmada."
            )

    @property
    def certificates(self) -> tuple[x509.Certificate, ...]:
        return self.anchors + self.links

    def issuers_of(self, certificate: x509.Certificate) -> list[x509.Certificate]:
        """Candidatos a emisor de `certificate`, anclas primero.

        Se filtra por DN sólo para reducir el conjunto: quien decide es la
        verificación de firma que hace quien construye la ruta. Las anclas van
        primero para que la ruta más corta —la que termina antes— se pruebe
        antes que la que pasa por eslabones.
        """
        return [
            candidate
            for candidate in self.certificates
            if candidate.subject == certificate.issuer
        ]

    def describe(self) -> dict:
        """Resumen para /health/ready. Huellas, nunca el material completo."""
        now = datetime.now(timezone.utc)
        return {
            "source": str(self.source),
            "anchors": len(self.anchors),
            "link_certificates": len(self.links),
            "anchor_details": [
                {
                    "subject": cert.subject.rfc4514_string(),
                    "sha256": cert.fingerprint(hashes.SHA256()).hex(),
                    "not_after": cert.not_valid_after_utc.isoformat(),
                    "expired": cert.not_valid_after_utc < now,
                }
                for cert in self.anchors
            ],
        }


def _is_self_signed(certificate: x509.Certificate) -> bool:
    """Raíz sí/no por firma. Ver el docstring del módulo sobre por qué no por DN."""
    if certificate.subject != certificate.issuer:
        return False
    try:
        certificate.verify_directly_issued_by(certificate)
    except Exception:
        return False
    return True


def _is_ca(certificate: x509.Certificate) -> bool:
    try:
        basic = certificate.extensions.get_extension_for_class(x509.BasicConstraints)
    except x509.ExtensionNotFound:
        # ICAO 9303-12 exige BasicConstraints en una CSCA. Sin la extensión no
        # se asume la capacidad más poderosa que un certificado puede tener.
        return False
    return bool(basic.value.ca)


def _parse(pem_bytes: bytes, source: Path) -> TrustStore:
    try:
        certificates = x509.load_pem_x509_certificates(pem_bytes)
    except Exception as exc:
        raise TrustStoreError(
            f"{source} no es un PEM de certificados válido: {exc}"
        ) from exc

    anchors: list[x509.Certificate] = []
    links: list[x509.Certificate] = []
    for certificate in certificates:
        if not _is_ca(certificate):
            # Un DSC (o cualquier hoja) colado en el trust store convertiría a
            # un firmante de documentos en autoridad. Se descarta con ruido.
            logger.warning(
                "Certificado sin BasicConstraints CA descartado del trust store: %s",
                certificate.subject.rfc4514_string(),
            )
            continue
        (anchors if _is_self_signed(certificate) else links).append(certificate)

    return TrustStore(anchors=tuple(anchors), links=tuple(links), source=source)


_lock = threading.Lock()
_cached: Optional[TrustStore] = None
_cached_path: Optional[Path] = None


def store_path() -> Path:
    configured = settings.CSCA_TRUST_STORE_PATH.strip()
    return Path(configured).expanduser() if configured else DEFAULT_TRUST_STORE


def load() -> TrustStore:
    """Trust store cargado y cacheado en proceso.

    Se cachea porque parsear y verificar la auto-firma de cada ancla en cada
    lectura NFC sería trabajo repetido sobre un archivo inmutable. La caché se
    invalida si cambia la ruta configurada; el contenido no se recarga en
    caliente a propósito: cambiar en qué se confía es un despliegue, no un
    efecto secundario de tocar un archivo.
    """
    global _cached, _cached_path

    path = store_path()
    cached = _cached
    if cached is not None and _cached_path == path:
        return cached

    with _lock:
        if _cached is not None and _cached_path == path:
            return _cached
        if not path.is_file():
            raise TrustStoreError(
                f"No existe el trust store de CSCA en {path}. Genéralo con "
                "`python backend/scripts/extract_csca_from_ldif.py <ldif> "
                "--country CL --out backend/app/certs/csca_chile.pem`."
            )
        store = _parse(path.read_bytes(), path)
        _cached = store
        _cached_path = path
        logger.info(
            "CSCA trust store cargado: %d anclas, %d link certificates (%s)",
            len(store.anchors),
            len(store.links),
            path,
        )
        return store


def reset_cache() -> None:
    """Sólo para tests: olvida el trust store cargado."""
    global _cached, _cached_path
    with _lock:
        _cached = None
        _cached_path = None


def status() -> dict:
    """Estado para readiness. Nunca lanza: un health check no debe caerse."""
    try:
        return {"available": True, "error": None, **load().describe()}
    except TrustStoreError as exc:
        return {
            "available": False,
            "error": str(exc),
            "source": str(store_path()),
            "anchors": 0,
            "link_certificates": 0,
            "anchor_details": [],
        }

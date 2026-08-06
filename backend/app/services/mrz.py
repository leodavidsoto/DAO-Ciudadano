"""
Lectura de la MRZ del DG1 (ICAO 9303 partes 5 y 6).

Se parsea en el servidor y no se confía en el JSON que el móvil derivó del
mismo chip: los bytes del DG1 vienen respaldados por la firma del SOD, el JSON
no. Un cliente puede mandar unos bytes auténticos y describirlos mal.

Sólo se extrae lo que hace falta para decidir si el documento sirve —país
emisor, tipo, caducidad— y el número que identifica establemente a la persona.
No se intenta adivinar nada más: los campos opcionales de la cédula chilena no
están documentados públicamente campo por campo, y rellenar un `rut` a ojo
sería inventar el dato más sensible del sistema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Valor de cada carácter en el algoritmo de dígito verificador de ICAO 9303.
_WEIGHTS = (7, 3, 1)
_FILLER = "<"


class MRZError(ValueError):
    """El DG1 no contiene una MRZ interpretable."""


@dataclass(frozen=True)
class MRZ:
    document_code: str
    issuing_state: str
    document_number: str
    nationality: str
    date_of_birth: str
    date_of_expiry: str
    sex: str
    #: Datos opcionales de la línea 1 (TD1) o `personalNumber` (TD3). En la
    #: cédula chilena es donde viaja el RUN.
    optional_data: str
    format: str

    @property
    def is_chilean(self) -> bool:
        return self.issuing_state == "CHL" and self.nationality == "CHL"

    @property
    def is_identity_card(self) -> bool:
        """`I`, `ID`, `IP`… La cédula; un pasaporte empieza por `P`."""
        return self.document_code.startswith("I")

    def expiry_date(self) -> Optional[date]:
        return _parse_yymmdd(self.date_of_expiry, expiry=True)

    def is_expired(self, today: Optional[date] = None) -> bool:
        expiry = self.expiry_date()
        if expiry is None:
            # Una caducidad ilegible no se interpreta como "no caduca".
            return True
        return expiry < (today or date.today())


def _check_digit(value: str) -> str:
    total = 0
    for index, character in enumerate(value):
        if character.isdigit():
            weight = int(character)
        elif character == _FILLER:
            weight = 0
        elif "A" <= character <= "Z":
            weight = ord(character) - 55
        else:
            raise MRZError(f"Carácter no válido en la MRZ: {character!r}")
        total += weight * _WEIGHTS[index % 3]
    return str(total % 10)


def _verify(field: str, digit: str, label: str) -> None:
    """Comprueba un dígito verificador de la MRZ.

    No es una comprobación de seguridad —la autenticidad la da la firma del
    SOD, que ya se verificó sobre estos mismos bytes— sino de que la MRZ se
    está troceando por donde corresponde. Si el corte estuviera mal, los
    dígitos no cuadrarían y es preferible fallar a leer el número de otro
    campo.
    """
    if digit == _FILLER:
        return
    if _check_digit(field) != digit:
        raise MRZError(f"El dígito verificador {label} no cuadra.")


def _parse_yymmdd(value: str, expiry: bool = False) -> Optional[date]:
    if not re.fullmatch(r"[0-9]{6}", value or ""):
        return None
    year, month, day = int(value[0:2]), int(value[2:4]), int(value[4:6])
    # ICAO no codifica el siglo. La convención para caducidades es que todo
    # apunta al futuro cercano; para nacimientos, al pasado.
    if expiry:
        century = 2000
    else:
        century = 2000 if year <= (date.today().year % 100) else 1900
    try:
        return date(century + year, month, day)
    except ValueError:
        return None


def _extract_mrz_string(dg1: bytes) -> str:
    """Saca la cadena MRZ del TLV del DG1 (`61` -> `5F1F`)."""
    if not dg1:
        raise MRZError("El DG1 llegó vacío.")

    # Se busca el tag 5F1F en vez de asumir desplazamientos fijos: la longitud
    # de la cabecera varía con el tamaño del archivo.
    marker = dg1.find(b"\x5f\x1f")
    if marker < 0:
        raise MRZError("El DG1 no contiene el campo 5F1F con la MRZ.")

    offset = marker + 2
    if offset >= len(dg1):
        raise MRZError("El DG1 está truncado.")
    length_byte = dg1[offset]
    offset += 1
    if length_byte & 0x80:
        count = length_byte & 0x7F
        if count == 0 or offset + count > len(dg1):
            raise MRZError("El DG1 tiene una longitud inválida.")
        length = int.from_bytes(dg1[offset : offset + count], "big")
        offset += count
    else:
        length = length_byte

    raw = dg1[offset : offset + length]
    if len(raw) != length:
        raise MRZError("El DG1 declara más MRZ de la que contiene.")
    return raw.decode("ascii", errors="replace").strip()


def parse(dg1: bytes) -> MRZ:
    """Interpreta el DG1 como MRZ TD1 (cédula) o TD3 (pasaporte)."""
    text = _extract_mrz_string(dg1)
    compact = "".join(text.split())

    if len(compact) == 90:
        return _parse_td1(compact)
    if len(compact) == 88:
        return _parse_td3(compact)
    if len(compact) == 72:
        return _parse_td2(compact)
    raise MRZError(
        f"La MRZ tiene {len(compact)} caracteres; no es TD1 (90), TD2 (72) ni TD3 (88)."
    )


def _parse_td1(mrz: str) -> MRZ:
    """Cédula de identidad: 3 líneas de 30."""
    line1, line2 = mrz[0:30], mrz[30:60]

    document_number = line1[5:14]
    _verify(document_number, line1[14], "del número de documento")

    date_of_birth = line2[0:6]
    _verify(date_of_birth, line2[6], "de la fecha de nacimiento")
    date_of_expiry = line2[8:14]
    _verify(date_of_expiry, line2[14], "de la fecha de caducidad")

    return MRZ(
        document_code=line1[0:2].replace(_FILLER, ""),
        issuing_state=line1[2:5].replace(_FILLER, ""),
        document_number=document_number.replace(_FILLER, ""),
        nationality=line2[15:18].replace(_FILLER, ""),
        date_of_birth=date_of_birth,
        date_of_expiry=date_of_expiry,
        sex=line2[7].replace(_FILLER, ""),
        # El RUN de la cédula chilena viaja aquí.
        optional_data=line1[15:30].replace(_FILLER, ""),
        format="TD1",
    )


def _parse_td2(mrz: str) -> MRZ:
    """TD2: 2 líneas de 36."""
    line1, line2 = mrz[0:36], mrz[36:72]

    document_number = line2[0:9]
    _verify(document_number, line2[9], "del número de documento")
    date_of_birth = line2[13:19]
    _verify(date_of_birth, line2[19], "de la fecha de nacimiento")
    date_of_expiry = line2[21:27]
    _verify(date_of_expiry, line2[27], "de la fecha de caducidad")

    return MRZ(
        document_code=line1[0:2].replace(_FILLER, ""),
        issuing_state=line1[2:5].replace(_FILLER, ""),
        document_number=document_number.replace(_FILLER, ""),
        nationality=line2[10:13].replace(_FILLER, ""),
        date_of_birth=date_of_birth,
        date_of_expiry=date_of_expiry,
        sex=line2[20].replace(_FILLER, ""),
        optional_data=line2[28:35].replace(_FILLER, ""),
        format="TD2",
    )


def _parse_td3(mrz: str) -> MRZ:
    """Pasaporte: 2 líneas de 44."""
    line1, line2 = mrz[0:44], mrz[44:88]

    document_number = line2[0:9]
    _verify(document_number, line2[9], "del número de documento")
    date_of_birth = line2[13:19]
    _verify(date_of_birth, line2[19], "de la fecha de nacimiento")
    date_of_expiry = line2[21:27]
    _verify(date_of_expiry, line2[27], "de la fecha de caducidad")

    personal_number = line2[28:42]
    _verify(personal_number, line2[42], "del número personal")

    return MRZ(
        document_code=line1[0:2].replace(_FILLER, ""),
        issuing_state=line1[2:5].replace(_FILLER, ""),
        document_number=document_number.replace(_FILLER, ""),
        nationality=line2[10:13].replace(_FILLER, ""),
        date_of_birth=date_of_birth,
        date_of_expiry=date_of_expiry,
        sex=line2[20].replace(_FILLER, ""),
        optional_data=personal_number.replace(_FILLER, ""),
        format="TD3",
    )

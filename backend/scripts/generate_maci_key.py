#!/usr/bin/env python3
"""
Genera y valida el par de llaves del coordinador MACI.

EJECÚTALO EN LA MÁQUINA DE QUIEN VA A CUSTODIAR LA LLAVE, no en un CI ni en
un agente automatizado. La llave privada que imprime descifra TODOS los votos
de toda consulta abierta bajo esa llave pública: quien la tenga puede leer la
papeleta de cualquier ciudadano.

No la escribe en ningún archivo ni la transmite. Solo la muestra una vez.

Uso:
    python scripts_generate_maci_key.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.maci_service import (  # noqa: E402
    coordinator_key_hash,
    generate_coordinator_keypair,
)

MACI_CONTRACT = "0x1CC218883dBeFf6aB8b4933723DF23B8F69336a6"


def main() -> None:
    private_key, (x, y) = generate_coordinator_keypair()

    print("=" * 72)
    print("LLAVE PRIVADA DEL COORDINADOR — descifra todos los votos")
    print("=" * 72)
    print(f"  {private_key}")
    print()
    print("  Guárdala en un gestor de secretos AHORA. No se puede recuperar,")
    print("  y perderla deja los votos ya emitidos permanentemente ilegibles.")
    print()
    print("=" * 72)
    print("LLAVE PÚBLICA — esto es lo que se publica on-chain")
    print("=" * 72)
    print(f"  x = {x}")
    print(f"  y = {y}")
    print(f"  Poseidon(x,y) = {coordinator_key_hash(x, y)}")
    print()
    print("Validada: pertenece a la curva Baby Jubjub y al subgrupo de orden")
    print("primo (misma comprobación que se aplica a las llaves de votantes).")
    print()
    print("Transacción a firmar con la wallet que tiene DEFAULT_ADMIN_ROLE:")
    print(f"  contrato: {MACI_CONTRACT}")
    print(f"  llamada : setCoordinatorPubKey({x}, {y})")
    print()
    print("ANTES DE EJECUTARLA, comprueba que tallyIsVerifiable() sea true.")
    print("Con el verificador de tally en address(0), publicar esta llave")
    print("habilita recibir votos que NADIE podrá contar de forma verificable.")


if __name__ == "__main__":
    main()

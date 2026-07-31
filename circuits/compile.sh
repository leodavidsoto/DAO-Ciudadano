#!/usr/bin/env bash
#
# Compila verify_identity.circom y genera las llaves Groth16.
#
# Requisitos (no se instalan solos):
#   - circom 2.x   -> https://docs.circom.io/getting-started/installation/
#   - snarkjs      -> npm install -g snarkjs
#   - circomlib    -> npm install   (en este directorio)
#
# Uso:  bash circuits/compile.sh
#
# NO ejecuta despliegues. Solo produce artefactos locales.
set -euo pipefail

CIRCUIT="verify_identity"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$DIR/build"
# Potencia del "powers of tau". 12 alcanza de sobra para este circuito
# (unos pocos miles de restricciones). Súbelo si el circuito crece.
PTAU_POWER=12

command -v circom  >/dev/null || { echo "ERROR: falta circom. Ver https://docs.circom.io"; exit 1; }
command -v snarkjs >/dev/null || { echo "ERROR: falta snarkjs. Corre: npm install -g snarkjs"; exit 1; }
[ -d "$DIR/node_modules/circomlib" ] || { echo "ERROR: falta circomlib. Corre: (cd circuits && npm install)"; exit 1; }

mkdir -p "$BUILD"
cd "$DIR"

echo "==> 1/6 Compilando el circuito"
circom "$CIRCUIT.circom" \
    --r1cs --wasm --sym \
    -l node_modules \
    -o "$BUILD"

echo "==> 2/6 Información del circuito (mira el número de restricciones: define el costo de gas)"
snarkjs r1cs info "$BUILD/$CIRCUIT.r1cs"

# El .ptau es la ceremonia universal (trusted setup fase 1). Es pesado y NO
# va al repositorio: se descarga o se regenera. Ver .gitignore.
PTAU="$BUILD/pot${PTAU_POWER}_final.ptau"
if [ ! -f "$PTAU" ]; then
    echo "==> 3/6 Generando powers of tau (solo la primera vez, tarda)"
    snarkjs powersoftau new bn128 "$PTAU_POWER" "$BUILD/pot_0000.ptau" -v
    snarkjs powersoftau contribute "$BUILD/pot_0000.ptau" "$BUILD/pot_0001.ptau" \
        --name="contribucion local dao-ciudadana" -v -e="$(head -c 32 /dev/urandom | base64)"
    snarkjs powersoftau prepare phase2 "$BUILD/pot_0001.ptau" "$PTAU" -v
else
    echo "==> 3/6 Reutilizando powers of tau existente"
fi

echo "==> 4/6 Setup Groth16 (fase 2)"
snarkjs groth16 setup "$BUILD/$CIRCUIT.r1cs" "$PTAU" "$BUILD/${CIRCUIT}_0000.zkey"

# ADVERTENCIA: esta contribución es de UNA sola parte, hecha en esta máquina.
# Para producción hace falta una ceremonia multi-parte real: si una sola
# persona conoce el "toxic waste", puede fabricar pruebas falsas.
snarkjs zkey contribute "$BUILD/${CIRCUIT}_0000.zkey" "$BUILD/${CIRCUIT}_final.zkey" \
    --name="contribucion local dao-ciudadana" -v -e="$(head -c 32 /dev/urandom | base64)"

echo "==> 5/6 Exportando la llave de verificación"
snarkjs zkey export verificationkey "$BUILD/${CIRCUIT}_final.zkey" "$BUILD/verification_key.json"

echo "==> 6/6 Exportando el contrato verificador en Solidity"
snarkjs zkey export solidityverifier "$BUILD/${CIRCUIT}_final.zkey" \
    "$DIR/../contracts/contracts/Verifier.sol"

cat <<EOF

Listo. Artefactos en circuits/build/:
  - ${CIRCUIT}_js/${CIRCUIT}.wasm   -> va empaquetado en el frontend (el prover lo necesita)
  - ${CIRCUIT}_final.zkey           -> va empaquetado en el frontend (llave de prueba)
  - verification_key.json           -> para verificar off-chain
  - contracts/contracts/Verifier.sol -> contrato verificador generado

RECORDATORIO: el .zkey de esta ceremonia local NO sirve para producción
(un solo participante). Antes de mainnet hace falta una ceremonia multi-parte.
EOF

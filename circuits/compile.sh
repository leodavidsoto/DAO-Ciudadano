#!/usr/bin/env bash
set -euo pipefail

# Rebuilds the development Groth16 artifacts for verify_identity.circom.
# This is an integration ceremony, not the production multi-party ceremony.

CIRCUIT="verify_identity"
CIRCUIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$CIRCUIT_DIR/build"
PTAU_POWER=15
CEREMONY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dao-ciudadana-zk.XXXXXX")"
COMPILED_DIR="$CEREMONY_DIR/compiled"

cleanup() {
    rm -rf "$CEREMONY_DIR"
}
trap cleanup EXIT

cd "$CIRCUIT_DIR"
mkdir -p "$BUILD_DIR"
mkdir -p "$COMPILED_DIR"

echo "==> 1/10 Compile and inspect circuit"
npx --no-install circom2 "$CIRCUIT.circom" \
    --r1cs --wasm --sym --inspect \
    -l node_modules \
    -o "$COMPILED_DIR"

echo "==> 2/10 Inspect R1CS"
npx --no-install snarkjs r1cs info "$COMPILED_DIR/$CIRCUIT.r1cs"

echo "==> 3/10 Create development Powers of Tau"
npx --no-install snarkjs powersoftau new \
    bn128 "$PTAU_POWER" "$CEREMONY_DIR/pot15_0000.ptau"
npx --no-install snarkjs powersoftau contribute \
    "$CEREMONY_DIR/pot15_0000.ptau" \
    "$CEREMONY_DIR/pot15_0001.ptau" \
    --name="dao-ciudadana-development-phase1" \
    -e="$(openssl rand -hex 64)"
npx --no-install snarkjs powersoftau prepare phase2 \
    "$CEREMONY_DIR/pot15_0001.ptau" \
    "$CEREMONY_DIR/pot15_final.ptau"

echo "==> 4/10 Circuit-specific Groth16 setup"
npx --no-install snarkjs groth16 setup \
    "$COMPILED_DIR/$CIRCUIT.r1cs" \
    "$CEREMONY_DIR/pot15_final.ptau" \
    "$CEREMONY_DIR/${CIRCUIT}_0000.zkey"

echo "==> 5/10 Add a development Phase 2 contribution"
npx --no-install snarkjs zkey contribute \
    "$CEREMONY_DIR/${CIRCUIT}_0000.zkey" \
    "$CEREMONY_DIR/${CIRCUIT}_final.zkey" \
    --name="dao-ciudadana-development-phase2" \
    -e="$(openssl rand -hex 64)"

echo "==> 6/10 Verify ceremony artifacts"
npx --no-install snarkjs powersoftau verify "$CEREMONY_DIR/pot15_final.ptau"
npx --no-install snarkjs zkey verify \
    "$COMPILED_DIR/$CIRCUIT.r1cs" \
    "$CEREMONY_DIR/pot15_final.ptau" \
    "$CEREMONY_DIR/${CIRCUIT}_final.zkey"

echo "==> 7/10 Export verification key and Solidity verifier"
npx --no-install snarkjs zkey export verificationkey \
    "$CEREMONY_DIR/${CIRCUIT}_final.zkey" \
    "$CEREMONY_DIR/verification_key.json"
npx --no-install snarkjs zkey export solidityverifier \
    "$CEREMONY_DIR/${CIRCUIT}_final.zkey" \
    "$CEREMONY_DIR/Verifier.sol"
# snarkjs' template emits whitespace-only padding on several lines. Removing
# it is formatting-only and keeps repository whitespace checks reproducible.
perl -pi -e 's/[ \t]+$//' "$CEREMONY_DIR/Verifier.sol"

cp "$CEREMONY_DIR/${CIRCUIT}_final.zkey" \
    "$BUILD_DIR/${CIRCUIT}_final.zkey"
cp "$CEREMONY_DIR/verification_key.json" \
    "$BUILD_DIR/verification_key.json"
cp "$CEREMONY_DIR/Verifier.sol" \
    "$CIRCUIT_DIR/../contracts/contracts/Verifier.sol"
mkdir -p "$BUILD_DIR/${CIRCUIT}_js"
cp "$COMPILED_DIR/${CIRCUIT}.r1cs" \
    "$BUILD_DIR/${CIRCUIT}.r1cs"
cp "$COMPILED_DIR/${CIRCUIT}.sym" \
    "$BUILD_DIR/${CIRCUIT}.sym"
cp "$COMPILED_DIR/${CIRCUIT}_js/${CIRCUIT}.wasm" \
    "$BUILD_DIR/${CIRCUIT}_js/${CIRCUIT}.wasm"
cp "$COMPILED_DIR/${CIRCUIT}_js/generate_witness.js" \
    "$BUILD_DIR/${CIRCUIT}_js/generate_witness.js"
cp "$COMPILED_DIR/${CIRCUIT}_js/witness_calculator.js" \
    "$BUILD_DIR/${CIRCUIT}_js/witness_calculator.js"

echo "==> 8/10 Generate a real integration proof fixture"
node "$CIRCUIT_DIR/scripts/generate-test-fixture.js"

echo "==> 9/10 Hash the exact client/verifier artifacts"
node "$CIRCUIT_DIR/scripts/generate-artifact-manifest.js"

echo "==> 10/10 Done"
echo "Development artifacts:"
echo "  circuits/build/${CIRCUIT}_js/${CIRCUIT}.wasm"
echo "  circuits/build/${CIRCUIT}_final.zkey"
echo "  circuits/build/verification_key.json"
echo "  contracts/contracts/Verifier.sol"
echo "WARNING: run a documented independent multi-party ceremony before production."

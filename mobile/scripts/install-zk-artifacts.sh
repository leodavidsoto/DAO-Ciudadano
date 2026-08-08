#!/usr/bin/env bash
set -euo pipefail

# Instala los artefactos del circuito MembershipEligibility(25) en el bundle
# nativo, junto con el prover snarkjs que los consume.
#
# No se versionan dentro de `mobile/`: pesan 8 MB y su única fuente es
# `circuits/build/`. Cada copia se verifica contra la huella publicada en
# `circuits/artifact-manifest.json` antes de entrar al bundle, porque un
# artefacto de otra compilación no rompe el build ni los tests: produce pruebas
# bien formadas que el verificador on-chain rechaza, y eso solo se descubre
# quemando gas en Sepolia. Aquí falla antes.
#
# Misma disciplina que `install-csca-master-list.sh`: en iOS se ejecuta como
# fase de build y copia dentro del `.app`; en Android escribe en la carpeta de
# assets, que el APK empaqueta.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$MOBILE_DIR/.." && pwd)"

MANIFEST="$REPO_ROOT/circuits/artifact-manifest.json"
ANDROID_ASSETS="$MOBILE_DIR/android/app/src/main/assets/zk"
PROVER_PAGE="$MOBILE_DIR/src/prover/prover.html"
SNARKJS_SOURCE="$MOBILE_DIR/node_modules/snarkjs/build/snarkjs.min.js"
SNARKJS_PACKAGE="$MOBILE_DIR/node_modules/snarkjs/package.json"

if [[ ! -f "$MANIFEST" ]]; then
  echo "error: falta $MANIFEST; sin él no hay huellas contra las que verificar" >&2
  exit 1
fi

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    sha256sum "$1" | cut -d' ' -f1
  fi
}

# Las claves de `files` son rutas con puntos ("…/verify_identity.wasm"), así que
# no se pueden partir por punto como el resto de las consultas.
manifest_sha256() {
  node -e '
    const manifest = require(process.argv[1]);
    const value = manifest.files?.[process.argv[2]]?.sha256;
    if (!value) process.exit(2);
    process.stdout.write(String(value));
  ' "$MANIFEST" "$1"
}

manifest_toolchain() {
  node -e '
    const manifest = require(process.argv[1]);
    const value = manifest.toolchain?.[process.argv[2]];
    if (!value) process.exit(2);
    process.stdout.write(String(value));
  ' "$MANIFEST" "$1"
}

# El zkey lo produjo una versión concreta de snarkjs. Probar con otra puede
# generar pruebas que el Verifier.sol desplegado no acepta, así que la versión
# es parte del artefacto, no un detalle de empaquetado.
EXPECTED_SNARKJS="$(manifest_toolchain snarkjs)"
if [[ ! -f "$SNARKJS_SOURCE" || ! -f "$SNARKJS_PACKAGE" ]]; then
  echo "error: falta snarkjs en mobile/node_modules; ejecuta npm ci en mobile/" >&2
  exit 1
fi
ACTUAL_SNARKJS="$(node -e 'process.stdout.write(require(process.argv[1]).version)' "$SNARKJS_PACKAGE")"
if [[ "$ACTUAL_SNARKJS" != "$EXPECTED_SNARKJS" ]]; then
  echo "error: snarkjs $ACTUAL_SNARKJS instalado, pero el zkey se generó con $EXPECTED_SNARKJS" >&2
  exit 1
fi

if [[ ! -f "$PROVER_PAGE" ]]; then
  echo "error: falta $PROVER_PAGE" >&2
  exit 1
fi

# Rutas relativas al repositorio: son también las claves del manifiesto.
CIRCUIT_ARTIFACTS=(
  "circuits/build/verify_identity_js/verify_identity.wasm"
  "circuits/build/verify_identity_final.zkey"
  "circuits/build/verification_key.json"
)

install_into() {
  local destination="$1"
  mkdir -p "$destination"

  local relative_path source_path expected actual
  for relative_path in "${CIRCUIT_ARTIFACTS[@]}"; do
    source_path="$REPO_ROOT/$relative_path"
    if [[ ! -s "$source_path" ]]; then
      echo "error: falta o está vacío $relative_path" >&2
      exit 1
    fi

    expected="$(manifest_sha256 "$relative_path" || true)"
    if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
      echo "error: el manifiesto no publica una huella SHA-256 de $relative_path" >&2
      exit 1
    fi
    actual="$(sha256_of "$source_path")"
    if [[ "$actual" != "$expected" ]]; then
      echo "error: $relative_path no coincide con el manifiesto" >&2
      echo "       esperado $expected" >&2
      echo "       obtenido $actual" >&2
      exit 1
    fi

    cp "$source_path" "$destination/$(basename "$relative_path")"
  done

  cp "$SNARKJS_SOURCE" "$destination/snarkjs.min.js"
  cp "$PROVER_PAGE" "$destination/prover.html"
}

install_into "$ANDROID_ASSETS"
echo "zk: artefactos instalados en android/app/src/main/assets/zk"

# En iOS solo hay destino cuando Xcode ejecuta este script como fase de build.
# Fuera de ese contexto no se inventa una ruta: se instala Android y se avisa.
if [[ -n "${TARGET_BUILD_DIR:-}" && -n "${UNLOCALIZED_RESOURCES_FOLDER_PATH:-}" ]]; then
  install_into "$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/zk"
  echo "zk: artefactos instalados en el bundle iOS"
else
  echo "zk: sin destino iOS (este script no corre como fase de build de Xcode)" >&2
fi

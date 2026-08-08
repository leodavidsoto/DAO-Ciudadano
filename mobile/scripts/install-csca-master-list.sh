#!/usr/bin/env bash
set -euo pipefail

# Instala la Master List en el bundle iOS sin incorporarla al repositorio.
# ICAO condiciona la redistribución de sus datos y el CSCA chileno requiere
# una procedencia aprobada; por eso el artefacto entra desde el entorno seguro
# del build y queda fijado por una huella obtenida por un canal independiente.

SOURCE_PATH="${DAO_CSCA_MASTER_LIST_PATH:-}"
EXPECTED_SHA256="${DAO_CSCA_MASTER_LIST_SHA256:-}"
DISTRIBUTION_BUILD="${DAO_MOBILE_DISTRIBUTION:-false}"

if [[ -z "$SOURCE_PATH" ]]; then
  if [[ -n "${TARGET_BUILD_DIR:-}" && -n "${UNLOCALIZED_RESOURCES_FOLDER_PATH:-}" ]]; then
    # An incremental build must not retain a trust store installed by an
    # earlier invocation after provisioning has been removed.
    rm -f "$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/cscaMasterList.pem"
  fi
  if [[ "$DISTRIBUTION_BUILD" == "true" ]]; then
    echo "error: falta DAO_CSCA_MASTER_LIST_PATH para el build de distribución" >&2
    exit 1
  fi
  echo "warning: build sin Master List CSCA; PassportReader fallará cerrado" >&2
  exit 0
fi

if [[ ! -f "$SOURCE_PATH" || ! -s "$SOURCE_PATH" ]]; then
  echo "error: la Master List CSCA no existe o está vacía" >&2
  exit 1
fi

NORMALIZED_SHA256="$(
  printf '%s' "$EXPECTED_SHA256" |
    tr -d ':' |
    tr '[:upper:]' '[:lower:]'
)"
if [[ ! "$NORMALIZED_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "error: DAO_CSCA_MASTER_LIST_SHA256 debe contener una huella SHA-256" >&2
  exit 1
fi

ACTUAL_SHA256="$(shasum -a 256 "$SOURCE_PATH" | awk '{print $1}')"
if [[ "$ACTUAL_SHA256" != "$NORMALIZED_SHA256" ]]; then
  echo "error: la huella SHA-256 de la Master List CSCA no coincide" >&2
  exit 1
fi

FILE_SIZE="$(wc -c < "$SOURCE_PATH" | tr -d ' ')"
if (( FILE_SIZE > 10000000 )); then
  echo "error: la Master List CSCA supera el máximo de 10 MB" >&2
  exit 1
fi

CERTIFICATES="$(
  openssl crl2pkcs7 -nocrl -certfile "$SOURCE_PATH" |
    openssl pkcs7 -print_certs -noout
)"
SUBJECTS="$(printf '%s\n' "$CERTIFICATES" | sed -n 's/^subject=//p')"
if [[ -z "$SUBJECTS" ]]; then
  echo "error: la Master List no expone sujetos X.509 verificables" >&2
  exit 1
fi
while IFS= read -r subject; do
  if ! printf '%s\n' "$subject" | grep -Eiq 'C[[:space:]]*=[[:space:]]*CL([,/]|$)'; then
    echo "error: la Master List contiene una ancla que no pertenece a Chile" >&2
    exit 1
  fi
done <<< "$SUBJECTS"
if ! printf '%s\n' "$CERTIFICATES" | grep -Eiq 'Servicio de Registro Civil'; then
  echo "error: la Master List no identifica al Registro Civil de Chile" >&2
  exit 1
fi

CERTIFICATE_COUNT="$(grep -c -- '-----BEGIN CERTIFICATE-----' "$SOURCE_PATH")"
if (( CERTIFICATE_COUNT < 1 )); then
  echo "error: la Master List CSCA no contiene certificados PEM" >&2
  exit 1
fi

CERT_INSPECTION_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dao-csca-inspection.XXXXXX")"
cleanup_certificate_inspection() {
  rm -rf -- "$CERT_INSPECTION_DIR"
}
trap cleanup_certificate_inspection EXIT

awk -v output_dir="$CERT_INSPECTION_DIR" '
  /-----BEGIN CERTIFICATE-----/ {
    certificate_count += 1
    output = sprintf("%s/certificate-%04d.pem", output_dir, certificate_count)
  }
  output != "" { print > output }
  /-----END CERTIFICATE-----/ { close(output); output = "" }
' "$SOURCE_PATH"

PARSED_CERTIFICATE_COUNT=0
for certificate in "$CERT_INSPECTION_DIR"/certificate-*.pem; do
  [[ -f "$certificate" ]] || continue
  PARSED_CERTIFICATE_COUNT=$((PARSED_CERTIFICATE_COUNT + 1))
  if ! openssl x509 -in "$certificate" -noout -text |
      grep -A 1 -E 'X509v3 Basic Constraints' |
      grep -Eq 'CA:[[:space:]]*TRUE'; then
    echo "error: la Master List contiene un certificado que no es una CSCA" >&2
    exit 1
  fi
done
if (( PARSED_CERTIFICATE_COUNT != CERTIFICATE_COUNT )); then
  echo "error: no se pudieron inspeccionar todos los certificados de la Master List" >&2
  exit 1
fi

if [[ -z "${TARGET_BUILD_DIR:-}" || -z "${UNLOCALIZED_RESOURCES_FOLDER_PATH:-}" ]]; then
  echo "error: este instalador debe ejecutarse dentro de un build de Xcode" >&2
  exit 1
fi

DESTINATION_DIR="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH"
DESTINATION="$DESTINATION_DIR/cscaMasterList.pem"
mkdir -p "$DESTINATION_DIR"
install -m 0644 "$SOURCE_PATH" "$DESTINATION"

echo "Master List CSCA instalada: $CERTIFICATE_COUNT certificado(s), SHA-256 $ACTUAL_SHA256"

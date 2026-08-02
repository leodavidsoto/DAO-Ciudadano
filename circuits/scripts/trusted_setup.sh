#!/usr/bin/env bash
set -Eeuo pipefail

# Groth16 Phase 2 for verify_identity.circom.
#
# This script validates the current circuit source, uses the public Hermez
# Powers of Tau transcript pinned by the snarkjs project, and creates one
# circuit-specific Phase 2 contribution. A production ceremony must pass the
# resulting zkey through independent participants; this script can validate and
# extend a previous participant's zkey with --input-zkey.

IFS=$'\n\t'
umask 077

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CIRCUIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
readonly CIRCUIT_NAME="verify_identity"
readonly CIRCUIT_SOURCE="$CIRCUIT_DIR/${CIRCUIT_NAME}.circom"

# Source and BLAKE2b-512 digest are published in the official snarkjs README:
# https://github.com/iden3/snarkjs#7-prepare-phase-2
readonly PTAU_FILENAME="powersOfTau28_hez_final_15.ptau"
readonly PTAU_URL="https://storage.googleapis.com/zkevm/ptau/${PTAU_FILENAME}"
readonly PTAU_BLAKE2B512="982372c867d229c236091f767e703253249a9b432c1710b4f326306bfa2428a17b06240359606cfe4d580b10a5a1f63fbed499527069c18ae17060472969ae6e"
readonly PTAU_BYTES="37831832"
readonly BEACON_ITERATIONS_EXPONENT="10"

# Both locations are ignored by the repository. Overrides exist for isolated
# tests, but are restricted to the same ignored trees.
readonly DEFAULT_CACHE_DIR="$CIRCUIT_DIR/.cache/trusted-setup"
readonly DEFAULT_OUTPUT_ROOT="$CIRCUIT_DIR/build/trusted-setup"
readonly CACHE_DIR="${TRUSTED_SETUP_CACHE_DIR:-$DEFAULT_CACHE_DIR}"
readonly OUTPUT_ROOT="${TRUSTED_SETUP_OUTPUT_ROOT:-$DEFAULT_OUTPUT_ROOT}"

readonly NODE_BIN="${TRUSTED_SETUP_NODE_BIN:-node}"
readonly CURL_BIN="${TRUSTED_SETUP_CURL_BIN:-curl}"
readonly CIRCOM_BIN="${TRUSTED_SETUP_CIRCOM_BIN:-$CIRCUIT_DIR/node_modules/.bin/circom2}"
readonly SNARKJS_BIN="${TRUSTED_SETUP_SNARKJS_BIN:-$CIRCUIT_DIR/node_modules/.bin/snarkjs}"

CONTRIBUTOR_NAME=""
CEREMONY_ID=""
INPUT_ZKEY=""
ENTROPY_FILE=""
BEACON_HEX=""
BEACON_NAME=""
WORK_DIR=""
DOWNLOAD_LOCK=""
LOCK_HELD=0
PTAU_PATH="$CACHE_DIR/$PTAU_FILENAME"

usage() {
    cat <<'EOF'
Usage:
  circuits/scripts/trusted_setup.sh --contributor-name NAME [options]

Required:
  --contributor-name NAME  Public label recorded in the Phase 2 transcript.

Options:
  --input-zkey FILE        Continue a zkey from a previous independent
                           participant. It is verified before contribution.
  --entropy-file FILE      Mix an operator-supplied secret (at least 32 bytes)
                           with OS randomness. The secret never appears in argv
                           or logs. Without this option, fresh OS randomness is
                           used non-interactively.
  --beacon HEX             Apply an explicit 32-byte public random beacon after
                           this contribution. Use only for the final ceremony
                           participant and document the beacon's future source.
  --beacon-name NAME       Public label for --beacon.
  --ceremony-id ID         Output directory name (letters, digits, . _ -).
  -h, --help               Show this help.

Outputs are published atomically under:
  circuits/build/trusted-setup/<ceremony-id>/

The script does not replace the zkey, verification key, or Solidity verifier
used by the application. Promotion must be a separately reviewed operation
that updates every protocol artifact together.

Example — first contributor:
  circuits/scripts/trusted_setup.sh \
    --contributor-name "Participant 1"

Example — later participant and final public beacon:
  circuits/scripts/trusted_setup.sh \
    --input-zkey /secure-transfer/verify_identity_phase2.zkey \
    --contributor-name "Participant 3" \
    --entropy-file /secure-local/participant-3.entropy \
    --beacon "$DOCUMENTED_PUBLIC_BEACON_HEX" \
    --beacon-name "Documented future public beacon"
EOF
}

log() {
    printf '==> %s\n' "$*" >&2
}

warn() {
    printf 'WARNING: %s\n' "$*" >&2
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_value() {
    local option="$1"
    local remaining="$2"

    if [[ "$remaining" -lt 2 ]]; then
        die "$option requires a value"
    fi
}

require_command() {
    local command_name="$1"

    if [[ "$command_name" == */* ]]; then
        [[ -x "$command_name" ]] || die "Required executable not found: $command_name"
    else
        command -v "$command_name" >/dev/null 2>&1 \
            || die "Required command not found: $command_name"
    fi
}

validate_public_label() {
    local label="$1"
    local field="$2"

    [[ -n "$label" ]] || die "$field cannot be empty"
    [[ "${#label}" -le 100 ]] || die "$field must be at most 100 characters"
    case "$label" in
        *$'\n'*|*$'\r'*|*$'\t'*)
            die "$field cannot contain control characters"
            ;;
    esac
}

validate_ignored_directory() {
    local path="$1"
    local allowed_prefix="$2"
    local field="$3"

    [[ "$path" == /* ]] || die "$field must be an absolute path"
    case "/$path/" in
        *"/../"*) die "$field cannot contain '..' path components" ;;
    esac
    case "$path/" in
        "$allowed_prefix"/*) ;;
        *) die "$field must stay inside $allowed_prefix" ;;
    esac
}

file_size() {
    "$NODE_BIN" -e \
        'process.stdout.write(String(require("fs").statSync(process.argv[1]).size))' \
        "$1"
}

file_hash() {
    local path="$1"
    local algorithm="$2"

    "$NODE_BIN" -e '
        const crypto = require("crypto");
        const fs = require("fs");
        const path = process.argv[1];
        const algorithm = process.argv[2];
        const hash = crypto.createHash(algorithm);
        const stream = fs.createReadStream(path);
        stream.on("data", (chunk) => hash.update(chunk));
        stream.on("error", (error) => {
            console.error(error.message);
            process.exitCode = 1;
        });
        stream.on("end", () => process.stdout.write(hash.digest("hex")));
    ' "$path" "$algorithm"
}

is_expected_ptau() {
    local path="$1"
    local actual_size
    local actual_hash

    [[ -f "$path" && ! -L "$path" ]] || return 1
    actual_size="$(file_size "$path")" || return 1
    [[ "$actual_size" == "$PTAU_BYTES" ]] || return 1
    actual_hash="$(file_hash "$path" blake2b512)" || return 1
    [[ "$actual_hash" == "$PTAU_BLAKE2B512" ]]
}

quarantine_file() {
    local path="$1"
    local quarantine_path

    quarantine_path="${path}.invalid.$(date -u +%Y%m%dT%H%M%SZ).$$"
    mv -- "$path" "$quarantine_path"
    warn "Rejected file preserved for inspection at $quarantine_path"
}

release_download_lock() {
    if [[ "$LOCK_HELD" -eq 1 && -n "$DOWNLOAD_LOCK" ]]; then
        rmdir -- "$DOWNLOAD_LOCK" 2>/dev/null || true
        LOCK_HELD=0
    fi
}

cleanup() {
    local exit_code="$?"
    trap - EXIT HUP INT TERM

    release_download_lock
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        case "$WORK_DIR" in
            "$OUTPUT_ROOT"/.*.tmp.*) rm -rf -- "$WORK_DIR" ;;
            *) warn "Refusing to remove unexpected temporary path: $WORK_DIR" ;;
        esac
    fi
    exit "$exit_code"
}
trap cleanup EXIT HUP INT TERM

download_and_verify_ptau() {
    local ptau_path="$PTAU_PATH"
    local partial_path="${ptau_path}.part"

    if is_expected_ptau "$ptau_path"; then
        log "Using checksum-verified cached Powers of Tau"
        return
    fi

    mkdir -p -- "$CACHE_DIR"
    [[ -d "$CACHE_DIR" && ! -L "$CACHE_DIR" ]] \
        || die "Cache directory must be a real directory: $CACHE_DIR"

    DOWNLOAD_LOCK="$CACHE_DIR/.download.lock"
    if ! mkdir -- "$DOWNLOAD_LOCK" 2>/dev/null; then
        die "Another download appears active ($DOWNLOAD_LOCK). Remove a stale lock only after checking no ceremony is running."
    fi
    LOCK_HELD=1

    # Another process may have populated the cache just before this lock.
    if is_expected_ptau "$ptau_path"; then
        release_download_lock
        log "Using checksum-verified cached Powers of Tau"
        return
    fi

    if [[ -e "$ptau_path" ]]; then
        [[ -f "$ptau_path" && ! -L "$ptau_path" ]] \
            || die "Refusing unexpected cache entry: $ptau_path"
        quarantine_file "$ptau_path"
    fi

    if is_expected_ptau "$partial_path"; then
        mv -- "$partial_path" "$ptau_path"
        release_download_lock
        log "Recovered a complete checksum-verified partial download"
        return
    fi

    if [[ -e "$partial_path" ]]; then
        [[ -f "$partial_path" && ! -L "$partial_path" ]] \
            || die "Refusing unexpected partial download: $partial_path"
        if [[ "$(file_size "$partial_path")" -gt "$PTAU_BYTES" ]]; then
            quarantine_file "$partial_path"
        fi
    fi

    log "Downloading public Powers of Tau (resumable, 37.8 MB)"
    "$CURL_BIN" \
        --fail \
        --location \
        --silent \
        --show-error \
        --proto '=https' \
        --proto-redir '=https' \
        --tlsv1.2 \
        --retry 5 \
        --retry-delay 2 \
        --connect-timeout 30 \
        --continue-at - \
        --output "$partial_path" \
        "$PTAU_URL"

    if ! is_expected_ptau "$partial_path"; then
        quarantine_file "$partial_path"
        die "Powers of Tau size or BLAKE2b-512 checksum did not match the pinned official value"
    fi

    mv -- "$partial_path" "$ptau_path"
    release_download_lock
    log "Powers of Tau checksum verified"
}

entropy_stream() {
    if [[ -n "$ENTROPY_FILE" ]]; then
        # Hash arbitrary file bytes into one line. snarkjs additionally mixes its
        # own crypto.randomFillSync() output before deriving the contribution.
        "$NODE_BIN" -e '
            const crypto = require("crypto");
            const fs = require("fs");
            const input = fs.readFileSync(process.argv[1]);
            process.stdout.write(crypto.createHash("sha512").update(input).digest("hex") + "\n");
        ' "$ENTROPY_FILE"
    else
        # Entropy travels over stdin, never via argv, environment, disk, or logs.
        "$NODE_BIN" -e \
            'process.stdout.write(require("crypto").randomBytes(64).toString("hex") + "\n")'
    fi
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --contributor-name)
            require_value "$1" "$#"
            CONTRIBUTOR_NAME="$2"
            shift 2
            ;;
        --input-zkey)
            require_value "$1" "$#"
            INPUT_ZKEY="$2"
            shift 2
            ;;
        --entropy-file)
            require_value "$1" "$#"
            ENTROPY_FILE="$2"
            shift 2
            ;;
        --beacon)
            require_value "$1" "$#"
            BEACON_HEX="$2"
            shift 2
            ;;
        --beacon-name)
            require_value "$1" "$#"
            BEACON_NAME="$2"
            shift 2
            ;;
        --ceremony-id)
            require_value "$1" "$#"
            CEREMONY_ID="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1 (use --help)"
            ;;
    esac
done

require_command "$NODE_BIN"
require_command "$CURL_BIN"
require_command "$CIRCOM_BIN"
require_command "$SNARKJS_BIN"

validate_public_label "$CONTRIBUTOR_NAME" "--contributor-name"

if [[ -z "$CEREMONY_ID" ]]; then
    CEREMONY_ID="$(date -u +%Y%m%dT%H%M%SZ)-$("$NODE_BIN" -e 'process.stdout.write(require("crypto").randomBytes(4).toString("hex"))')"
fi
[[ "$CEREMONY_ID" =~ ^[A-Za-z0-9._-]{1,64}$ ]] \
    || die "--ceremony-id must contain 1-64 letters, digits, dots, underscores, or hyphens"

if [[ -n "$BEACON_HEX" ]]; then
    [[ "$BEACON_HEX" =~ ^[0-9A-Fa-f]{64}$ ]] \
        || die "--beacon must be exactly 64 hexadecimal characters"
    if [[ -z "$BEACON_NAME" ]]; then
        BEACON_NAME="$CONTRIBUTOR_NAME final public beacon"
    fi
    validate_public_label "$BEACON_NAME" "--beacon-name"
elif [[ -n "$BEACON_NAME" ]]; then
    die "--beacon-name requires --beacon"
fi

if [[ -n "$INPUT_ZKEY" ]]; then
    [[ -f "$INPUT_ZKEY" && ! -L "$INPUT_ZKEY" && -r "$INPUT_ZKEY" ]] \
        || die "--input-zkey must be a readable regular file, not a symlink"
fi

if [[ -n "$ENTROPY_FILE" ]]; then
    [[ -f "$ENTROPY_FILE" && ! -L "$ENTROPY_FILE" && -r "$ENTROPY_FILE" ]] \
        || die "--entropy-file must be a readable regular file, not a symlink"
    entropy_bytes="$(file_size "$ENTROPY_FILE")"
    [[ "$entropy_bytes" -ge 32 && "$entropy_bytes" -le 65536 ]] \
        || die "--entropy-file must contain between 32 and 65536 bytes"
fi

validate_ignored_directory "$CACHE_DIR" "$CIRCUIT_DIR/.cache" "TRUSTED_SETUP_CACHE_DIR"
validate_ignored_directory "$OUTPUT_ROOT" "$CIRCUIT_DIR/build" "TRUSTED_SETUP_OUTPUT_ROOT"

[[ -f "$CIRCUIT_SOURCE" && ! -L "$CIRCUIT_SOURCE" ]] \
    || die "Circuit source not found or is a symlink: $CIRCUIT_SOURCE"

mkdir -p -- "$OUTPUT_ROOT"
[[ -d "$OUTPUT_ROOT" && ! -L "$OUTPUT_ROOT" ]] \
    || die "Output root must be a real directory: $OUTPUT_ROOT"

FINAL_DIR="$OUTPUT_ROOT/$CEREMONY_ID"
[[ ! -e "$FINAL_DIR" ]] || die "Ceremony output already exists: $FINAL_DIR"

WORK_DIR="$(mktemp -d "$OUTPUT_ROOT/.${CEREMONY_ID}.tmp.XXXXXX")"
SCRATCH_DIR="$WORK_DIR/.scratch"
COMPILED_DIR="$SCRATCH_DIR/compiled"
mkdir -p -- "$COMPILED_DIR"

log "1/8 Fetch and authenticate the public Phase 1 transcript"
download_and_verify_ptau
"$SNARKJS_BIN" powersoftau verify "$PTAU_PATH"

log "2/8 Compile and inspect the current circuit"
"$CIRCOM_BIN" "$CIRCUIT_SOURCE" \
    --r1cs \
    --sym \
    --inspect \
    -l "$CIRCUIT_DIR/node_modules" \
    -o "$COMPILED_DIR"

R1CS_PATH="$COMPILED_DIR/${CIRCUIT_NAME}.r1cs"
SYM_PATH="$COMPILED_DIR/${CIRCUIT_NAME}.sym"
[[ -s "$R1CS_PATH" && -s "$SYM_PATH" ]] \
    || die "Circuit compiler did not produce the expected R1CS and symbol files"
"$SNARKJS_BIN" r1cs info "$R1CS_PATH"

log "3/8 Establish a verified Phase 2 starting point"
if [[ -n "$INPUT_ZKEY" ]]; then
    STARTING_ZKEY="$SCRATCH_DIR/participant-input.zkey"
    cp -- "$INPUT_ZKEY" "$STARTING_ZKEY"
    "$SNARKJS_BIN" zkey verify "$R1CS_PATH" "$PTAU_PATH" "$STARTING_ZKEY"
    INPUT_ZKEY_SHA256="$(file_hash "$STARTING_ZKEY" sha256)"
    INPUT_DESCRIPTION="independent-participant:${INPUT_ZKEY_SHA256}"
else
    STARTING_ZKEY="$SCRATCH_DIR/${CIRCUIT_NAME}_0000.zkey"
    "$SNARKJS_BIN" groth16 setup "$R1CS_PATH" "$PTAU_PATH" "$STARTING_ZKEY"
    INPUT_ZKEY_SHA256="none"
    INPUT_DESCRIPTION="local-zero-contribution-bootstrap"
fi
[[ -s "$STARTING_ZKEY" ]] || die "Phase 2 starting zkey was not created"

log "4/8 Add this participant's non-interactive contribution"
CONTRIBUTED_ZKEY="$SCRATCH_DIR/${CIRCUIT_NAME}_contributed.zkey"
entropy_stream | "$SNARKJS_BIN" zkey contribute \
    "$STARTING_ZKEY" \
    "$CONTRIBUTED_ZKEY" \
    --name="$CONTRIBUTOR_NAME"
[[ -s "$CONTRIBUTED_ZKEY" ]] || die "snarkjs did not create the contributed zkey"

log "5/8 Apply final beacon when explicitly requested"
PHASE2_ZKEY="$WORK_DIR/${CIRCUIT_NAME}_phase2.zkey"
if [[ -n "$BEACON_HEX" ]]; then
    "$SNARKJS_BIN" zkey beacon \
        "$CONTRIBUTED_ZKEY" \
        "$PHASE2_ZKEY" \
        "$BEACON_HEX" \
        "$BEACON_ITERATIONS_EXPONENT" \
        --name="$BEACON_NAME"
    BEACON_DESCRIPTION="applied:${BEACON_HEX}:2^${BEACON_ITERATIONS_EXPONENT}:${BEACON_NAME}"
else
    mv -- "$CONTRIBUTED_ZKEY" "$PHASE2_ZKEY"
    BEACON_DESCRIPTION="not-applied"
fi

log "6/8 Verify the complete contribution chain against circuit and ptau"
"$SNARKJS_BIN" zkey verify "$R1CS_PATH" "$PTAU_PATH" "$PHASE2_ZKEY"

log "7/8 Export review artifacts and a reproducibility receipt"
VERIFICATION_KEY="$WORK_DIR/verification_key.json"
SOLIDITY_VERIFIER="$WORK_DIR/Verifier.sol"
"$SNARKJS_BIN" zkey export verificationkey "$PHASE2_ZKEY" "$VERIFICATION_KEY"
"$SNARKJS_BIN" zkey export solidityverifier "$PHASE2_ZKEY" "$SOLIDITY_VERIFIER"
[[ -s "$VERIFICATION_KEY" && -s "$SOLIDITY_VERIFIER" ]] \
    || die "snarkjs did not export the verification artifacts"

cp -- "$R1CS_PATH" "$WORK_DIR/${CIRCUIT_NAME}.r1cs"
cp -- "$SYM_PATH" "$WORK_DIR/${CIRCUIT_NAME}.sym"

R1CS_SHA256="$(file_hash "$WORK_DIR/${CIRCUIT_NAME}.r1cs" sha256)"
ZKEY_SHA256="$(file_hash "$PHASE2_ZKEY" sha256)"
VKEY_SHA256="$(file_hash "$VERIFICATION_KEY" sha256)"
VERIFIER_SHA256="$(file_hash "$SOLIDITY_VERIFIER" sha256)"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$WORK_DIR/ceremony-manifest.txt" <<EOF
protocol=groth16-bn128-phase2
circuit=${CIRCUIT_NAME}
created_at=${CREATED_AT}
contributor=${CONTRIBUTOR_NAME}
starting_zkey=${INPUT_DESCRIPTION}
beacon=${BEACON_DESCRIPTION}
ptau_url=${PTAU_URL}
ptau_bytes=${PTAU_BYTES}
ptau_blake2b512=${PTAU_BLAKE2B512}
r1cs_sha256=${R1CS_SHA256}
zkey_sha256=${ZKEY_SHA256}
verification_key_sha256=${VKEY_SHA256}
solidity_verifier_sha256=${VERIFIER_SHA256}
participant_independence=not-attested-by-script
promotion_status=not-promoted
EOF

chmod 600 \
    "$PHASE2_ZKEY" \
    "$VERIFICATION_KEY" \
    "$SOLIDITY_VERIFIER" \
    "$WORK_DIR/${CIRCUIT_NAME}.r1cs" \
    "$WORK_DIR/${CIRCUIT_NAME}.sym" \
    "$WORK_DIR/ceremony-manifest.txt"

# Do not publish the zero-contribution zkey, copied participant input, or any
# temporary entropy material. The path guard makes this recursive deletion
# specific to the mktemp directory created above.
case "$SCRATCH_DIR" in
    "$WORK_DIR/.scratch") rm -rf -- "$SCRATCH_DIR" ;;
    *) die "Refusing to clean unexpected scratch directory: $SCRATCH_DIR" ;;
esac

log "8/8 Atomically publish this ceremony result"
mv -- "$WORK_DIR" "$FINAL_DIR"
WORK_DIR=""

printf '\nPhase 2 contribution verified and published at:\n  %s\n' "$FINAL_DIR"
printf 'Continue the ceremony with:\n  %s --input-zkey %s/%s_phase2.zkey --contributor-name "Next participant"\n' \
    "$SCRIPT_DIR/trusted_setup.sh" \
    "$FINAL_DIR" \
    "$CIRCUIT_NAME"
warn "Transcript integrity was verified, but participant independence cannot be automated. Do not promote these artifacts until the documented multi-party ceremony and external circuit audit are complete."

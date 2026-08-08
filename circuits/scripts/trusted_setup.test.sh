#!/usr/bin/env bash
set -Eeuo pipefail

IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CIRCUIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
readonly SUBJECT="$SCRIPT_DIR/trusted_setup.sh"
readonly TEST_ID="trusted-setup-test-$$"
readonly CACHE_DIR="$CIRCUIT_DIR/.cache/$TEST_ID"
readonly OUTPUT_ROOT="$CIRCUIT_DIR/build/$TEST_ID"
readonly TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/dao-trusted-setup-test.XXXXXX")"
readonly MOCK_BIN="$TEST_TMP/bin"
readonly MOCK_LOG="$TEST_TMP/snarkjs.log"
readonly CEREMONY_ID="mock-ceremony"
readonly FINAL_DIR="$OUTPUT_ROOT/$CEREMONY_ID"
readonly FINAL_CEREMONY_ID="mock-ceremony-final"
readonly FINAL_BEACON="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
readonly ENTROPY_FILE="$TEST_TMP/operator.entropy"

cleanup() {
    local exit_code="$?"
    trap - EXIT HUP INT TERM
    case "$TEST_TMP" in
        "${TMPDIR:-/tmp}"/dao-trusted-setup-test.*) rm -rf -- "$TEST_TMP" ;;
    esac
    case "$CACHE_DIR" in
        "$CIRCUIT_DIR/.cache/$TEST_ID") rm -rf -- "$CACHE_DIR" ;;
    esac
    case "$OUTPUT_ROOT" in
        "$CIRCUIT_DIR/build/$TEST_ID") rm -rf -- "$OUTPUT_ROOT" ;;
    esac
    exit "$exit_code"
}
trap cleanup EXIT HUP INT TERM

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

mkdir -p -- "$MOCK_BIN"

cat > "$MOCK_BIN/node" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

program="${2:-}"
if [[ "$program" == *"statSync"* ]]; then
    case "${3:-}" in
        *operator.entropy) printf '48' ;;
        *) printf '37831832' ;;
    esac
elif [[ "$program" == *"createReadStream"* ]]; then
    algorithm="${4:-}"
    if [[ "$algorithm" == "blake2b512" ]]; then
        printf '982372c867d229c236091f767e703253249a9b432c1710b4f326306bfa2428a17b06240359606cfe4d580b10a5a1f63fbed499527069c18ae17060472969ae6e'
    else
        printf '0000000000000000000000000000000000000000000000000000000000000000'
    fi
elif [[ "$program" == *"randomBytes(64)"* ]]; then
    printf '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n'
elif [[ "$program" == *"readFileSync"* && "$program" == *"sha512"* ]]; then
    printf 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789\n'
else
    printf 'mock-node: unsupported invocation\n' >&2
    exit 2
fi
EOF

cat > "$MOCK_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

output=""
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --output)
            output="$2"
            shift 2
            ;;
        *) shift ;;
    esac
done
[[ -n "$output" ]]
printf 'mock authenticated ptau\n' > "$output"
EOF

cat > "$MOCK_BIN/circom2" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

output=""
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -o)
            output="$2"
            shift 2
            ;;
        *) shift ;;
    esac
done
[[ -n "$output" ]]
mkdir -p -- "$output"
printf 'mock r1cs\n' > "$output/verify_identity.r1cs"
printf 'mock symbols\n' > "$output/verify_identity.sym"
EOF

cat > "$MOCK_BIN/snarkjs" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >> "$MOCK_LOG"
case "${1:-} ${2:-}" in
    "powersoftau verify"|"r1cs info"|"zkey verify")
        ;;
    "groth16 setup")
        printf 'mock initial zkey\n' > "$5"
        ;;
    "zkey contribute")
        IFS= read -r entropy
        [[ "${#entropy}" -ge 64 ]]
        printf 'mock contributed zkey\n' > "$4"
        ;;
    "zkey beacon")
        printf 'mock beacon zkey\n' > "$4"
        ;;
    "zkey export")
        case "${3:-}" in
            verificationkey) printf '{"protocol":"groth16"}\n' > "$5" ;;
            solidityverifier) printf 'contract Verifier {}\n' > "$5" ;;
            *) exit 2 ;;
        esac
        ;;
    *)
        printf 'mock-snarkjs: unsupported invocation: %s\n' "$*" >&2
        exit 2
        ;;
esac
EOF

chmod 755 "$MOCK_BIN/node" "$MOCK_BIN/curl" "$MOCK_BIN/circom2" "$MOCK_BIN/snarkjs"

export MOCK_LOG
TRUSTED_SETUP_CACHE_DIR="$CACHE_DIR" \
TRUSTED_SETUP_OUTPUT_ROOT="$OUTPUT_ROOT" \
TRUSTED_SETUP_NODE_BIN="$MOCK_BIN/node" \
TRUSTED_SETUP_CURL_BIN="$MOCK_BIN/curl" \
TRUSTED_SETUP_CIRCOM_BIN="$MOCK_BIN/circom2" \
TRUSTED_SETUP_SNARKJS_BIN="$MOCK_BIN/snarkjs" \
    "$SUBJECT" \
        --contributor-name "Automated test participant" \
        --ceremony-id "$CEREMONY_ID" \
        > "$TEST_TMP/stdout.log" \
        2> "$TEST_TMP/stderr.log"

[[ -s "$FINAL_DIR/verify_identity_phase2.zkey" ]] \
    || fail "final Phase 2 zkey was not atomically published"
[[ -s "$FINAL_DIR/verification_key.json" ]] \
    || fail "verification key was not exported"
[[ -s "$FINAL_DIR/Verifier.sol" ]] \
    || fail "Solidity verifier was not exported"
[[ -s "$FINAL_DIR/ceremony-manifest.txt" ]] \
    || fail "ceremony receipt was not written"
[[ ! -e "$FINAL_DIR/.scratch" ]] \
    || fail "private scratch artifacts were published"
[[ ! -e "$FINAL_DIR/verify_identity_0000.zkey" ]] \
    || fail "unsafe zero-contribution zkey was published"

grep -q '^ptau_blake2b512=982372c867d229c236091f767e703253' \
    "$FINAL_DIR/ceremony-manifest.txt" \
    || fail "pinned BLAKE2b-512 digest is missing from receipt"
grep -q '^participant_independence=not-attested-by-script$' \
    "$FINAL_DIR/ceremony-manifest.txt" \
    || fail "receipt overclaims participant independence"
grep -q '^promotion_status=not-promoted$' "$FINAL_DIR/ceremony-manifest.txt" \
    || fail "receipt overclaims promotion status"
grep -q '^powersoftau verify ' "$MOCK_LOG" \
    || fail "Powers of Tau transcript was not cryptographically verified"
grep -q '^zkey verify ' "$MOCK_LOG" \
    || fail "final zkey was not verified"

printf 'independent operator entropy with more than 32 bytes\n' > "$ENTROPY_FILE"
TRUSTED_SETUP_CACHE_DIR="$CACHE_DIR" \
TRUSTED_SETUP_OUTPUT_ROOT="$OUTPUT_ROOT" \
TRUSTED_SETUP_NODE_BIN="$MOCK_BIN/node" \
TRUSTED_SETUP_CURL_BIN="$MOCK_BIN/curl" \
TRUSTED_SETUP_CIRCOM_BIN="$MOCK_BIN/circom2" \
TRUSTED_SETUP_SNARKJS_BIN="$MOCK_BIN/snarkjs" \
    "$SUBJECT" \
        --input-zkey "$FINAL_DIR/verify_identity_phase2.zkey" \
        --contributor-name "Independent final participant" \
        --entropy-file "$ENTROPY_FILE" \
        --beacon "$FINAL_BEACON" \
        --beacon-name "Test public beacon" \
        --ceremony-id "$FINAL_CEREMONY_ID" \
        > "$TEST_TMP/final-stdout.log" \
        2> "$TEST_TMP/final-stderr.log"

FINAL_CEREMONY_DIR="$OUTPUT_ROOT/$FINAL_CEREMONY_ID"
[[ -s "$FINAL_CEREMONY_DIR/verify_identity_phase2.zkey" ]] \
    || fail "continued ceremony zkey was not published"
grep -q '^starting_zkey=independent-participant:' \
    "$FINAL_CEREMONY_DIR/ceremony-manifest.txt" \
    || fail "previous participant zkey was not recorded"
grep -q "^beacon=applied:${FINAL_BEACON}:2\^10:Test public beacon$" \
    "$FINAL_CEREMONY_DIR/ceremony-manifest.txt" \
    || fail "explicit public beacon was not recorded"
grep -q '^zkey beacon ' "$MOCK_LOG" \
    || fail "explicit final beacon was not applied"

if TRUSTED_SETUP_CACHE_DIR="$CACHE_DIR" \
    TRUSTED_SETUP_OUTPUT_ROOT="$OUTPUT_ROOT" \
    TRUSTED_SETUP_NODE_BIN="$MOCK_BIN/node" \
    TRUSTED_SETUP_CURL_BIN="$MOCK_BIN/curl" \
    TRUSTED_SETUP_CIRCOM_BIN="$MOCK_BIN/circom2" \
    TRUSTED_SETUP_SNARKJS_BIN="$MOCK_BIN/snarkjs" \
        "$SUBJECT" \
            --contributor-name "Automated test participant" \
            --ceremony-id "$CEREMONY_ID" \
            > "$TEST_TMP/retry-stdout.log" \
            2> "$TEST_TMP/retry-stderr.log"; then
    fail "existing ceremony output was overwritten"
fi
grep -q 'Ceremony output already exists' "$TEST_TMP/retry-stderr.log" \
    || fail "existing-output failure was not explicit"

printf 'trusted_setup.test.sh: PASS\n'

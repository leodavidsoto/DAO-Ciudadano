#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
MOBILE_DIR="$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)"
: "${DAO_VERSION_NAME:?DAO_VERSION_NAME is required}"
: "${DAO_VERSION_CODE:?DAO_VERSION_CODE is required}"
: "${DAO_ANDROID_CERT_SHA256:?DAO_ANDROID_CERT_SHA256 is required}"
: "${ANDROID_SDK_ROOT:?ANDROID_SDK_ROOT is required}"

cd "$MOBILE_DIR"
npm run config:release

cd android
./gradlew \
  --no-daemon \
  --stacktrace \
  --console=plain \
  --dependency-verification=strict \
  :app:lintRelease \
  :app:testReleaseUnitTest \
  :app:assembleRelease \
  :app:validateReleaseBundle \
  -PdaoVersionName="$DAO_VERSION_NAME" \
  -PdaoVersionCode="$DAO_VERSION_CODE"

APK="app/build/outputs/apk/release/app-release.apk"
AAB="app/build/outputs/bundle/release/app-release.aab"
test -s "$APK"
test -s "$AAB"

AAPT2="$ANDROID_SDK_ROOT/build-tools/36.0.0/aapt2"
APK_SIGNER="$ANDROID_SDK_ROOT/build-tools/36.0.0/apksigner"
ZIPALIGN="$ANDROID_SDK_ROOT/build-tools/36.0.0/zipalign"
test -x "$AAPT2"
test -x "$APK_SIGNER"
test -x "$ZIPALIGN"

"$ZIPALIGN" -c -P 16 4 "$APK"

APK_BADGING="$("$AAPT2" dump badging "$APK")"
grep -Fq \
  "package: name='com.daociudadanaapp' versionCode='$DAO_VERSION_CODE' versionName='$DAO_VERSION_NAME'" \
  <<< "$APK_BADGING"
grep -Fqx "targetSdkVersion:'34'" <<< "$APK_BADGING"
grep -Fqx "uses-permission: name='android.permission.NFC'" <<< "$APK_BADGING"
if grep -q '^application-debuggable' <<< "$APK_BADGING"; then
  echo 'Release APK must not be debuggable.' >&2
  exit 1
fi
APK_NATIVE_CODE="$(grep '^native-code:' <<< "$APK_BADGING")"
for architecture in armeabi-v7a arm64-v8a x86 x86_64; do
  grep -Fq "'$architecture'" <<< "$APK_NATIVE_CODE"
done

EXPECTED_CERT_SHA256="$(
  printf '%s' "$DAO_ANDROID_CERT_SHA256" |
    tr -d ':' |
    tr '[:upper:]' '[:lower:]'
)"
APK_SIGNER_OUTPUT="$("$APK_SIGNER" verify --verbose --print-certs "$APK")"
APK_CERT_SHA256="$(
  awk -F': ' '/Signer #1 certificate SHA-256 digest:/{print $2; exit}' \
    <<< "$APK_SIGNER_OUTPUT" |
    tr -d ':' |
    tr '[:upper:]' '[:lower:]'
)"
test -n "$APK_CERT_SHA256"
test "$APK_CERT_SHA256" = "$EXPECTED_CERT_SHA256"

JARSIGNER_OUTPUT="$(jarsigner -verify "$AAB" 2>&1)"
if ! grep -qx 'jar verified\.' <<< "$JARSIGNER_OUTPUT"; then
  printf '%s\n' "$JARSIGNER_OUTPUT" >&2
  exit 1
fi
printf 'AAB JAR signature verified.\n'
AAB_CERT_SHA256="$(
  keytool -printcert -jarfile "$AAB" |
    awk -F': ' '/^[[:space:]]*SHA256:/{print $2; exit}' |
    tr -d ':' |
    tr '[:upper:]' '[:lower:]'
)"
test -n "$AAB_CERT_SHA256"
test "$AAB_CERT_SHA256" = "$EXPECTED_CERT_SHA256"
shasum -a 256 "$APK" "$AAB"

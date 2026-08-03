#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
MOBILE_DIR="$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)"
VERSION_NAME="${DAO_VERSION_NAME:-1.0.0-ci}"
VERSION_CODE="${DAO_VERSION_CODE:-1}"
ANDROID_ARCHITECTURES="${DAO_ANDROID_ARCHITECTURES:-armeabi-v7a,arm64-v8a,x86,x86_64}"

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
  -PdaoAllowUnsignedRelease=true \
  -PdaoVersionName="$VERSION_NAME" \
  -PdaoVersionCode="$VERSION_CODE" \
  -PreactNativeArchitectures="$ANDROID_ARCHITECTURES"

APK="app/build/outputs/apk/release/app-release-unsigned.apk"
AAB="app/build/outputs/bundle/release/app-release.aab"
test -s "$APK"
test -s "$AAB"

: "${ANDROID_SDK_ROOT:?ANDROID_SDK_ROOT is required}"
AAPT2="$ANDROID_SDK_ROOT/build-tools/36.0.0/aapt2"
ZIPALIGN="$ANDROID_SDK_ROOT/build-tools/36.0.0/zipalign"
test -x "$AAPT2"
test -x "$ZIPALIGN"

"$ZIPALIGN" -c -P 16 4 "$APK"

APK_BADGING="$("$AAPT2" dump badging "$APK")"
grep -Fq \
  "package: name='com.daociudadanaapp' versionCode='$VERSION_CODE' versionName='$VERSION_NAME'" \
  <<< "$APK_BADGING"
grep -Fqx "targetSdkVersion:'36'" <<< "$APK_BADGING"
grep -Fqx "uses-permission: name='android.permission.NFC'" <<< "$APK_BADGING"
if grep -q '^application-debuggable' <<< "$APK_BADGING"; then
  echo 'Release APK must not be debuggable.' >&2
  exit 1
fi
APK_NATIVE_CODE="$(grep '^native-code:' <<< "$APK_BADGING")"
for architecture in ${ANDROID_ARCHITECTURES//,/ }; do
  grep -Fq "'$architecture'" <<< "$APK_NATIVE_CODE"
done

shasum -a 256 "$APK" "$AAB"

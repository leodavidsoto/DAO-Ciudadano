#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
MOBILE_DIR="$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)"
DERIVED_DATA_PATH="${DAO_IOS_DERIVED_DATA_PATH:-$MOBILE_DIR/ios/build/DerivedData}"
EXPECTED_XCODE_VERSION="${DAO_XCODE_VERSION:-16.4}"
EXPECTED_XCODE_BUILD="${DAO_XCODE_BUILD:-16F6}"

cd "$MOBILE_DIR"
npm run config:release

XCODE_VERSION_OUTPUT="$(xcodebuild -version)"
printf '%s\n' "$XCODE_VERSION_OUTPUT"
printf '%s\n' "$XCODE_VERSION_OUTPUT" | grep -qx "Xcode $EXPECTED_XCODE_VERSION"
printf '%s\n' "$XCODE_VERSION_OUTPUT" | grep -qx "Build version $EXPECTED_XCODE_BUILD"

bundle exec pod install --project-directory=ios --deployment

xcodebuild \
  -workspace ios/DAOCiudadanaApp.xcworkspace \
  -scheme DAOCiudadanaApp \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  COMPILER_INDEX_STORE_ENABLE=NO \
  clean build

APP="$DERIVED_DATA_PATH/Build/Products/Release-iphoneos/DAOCiudadanaApp.app"
test -d "$APP"
test -s "$APP/main.jsbundle"
test -s "$APP/PrivacyInfo.xcprivacy"
plutil -lint "$APP/Info.plist" "$APP/PrivacyInfo.xcprivacy"
test -n "$(/usr/libexec/PlistBuddy -c 'Print :NFCReaderUsageDescription' "$APP/Info.plist")"
APP_EXECUTABLE="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Info.plist")"
/usr/bin/lipo -verify_arch arm64 "$APP/$APP_EXECUTABLE"
printf 'Unsigned iOS Release device app: %s\n' "$APP"

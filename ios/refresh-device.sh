#!/bin/zsh
# Rebuild Locus and reinstall it on the iPhone, renewing the signing profile.
#
# Apple expires a personally-signed app's provisioning profile — 7 days on a free
# Apple ID, a year on a paid one — after which the app simply stops launching.
# Nothing in this repo can extend that; the only fix is to sign and install again.
# This script is that chore reduced to one command, run from Sharad Launchpad's
# "Locus on iPhone" card.
#
#   ./ios/refresh-device.sh              build and install
#   ./ios/refresh-device.sh --launch     also open the app on the phone
#
# The phone must be unlocked and reachable — plugged in, or on the same wifi with
# "Connect via Network" ticked in Xcode > Window > Devices and Simulators.
set -e
cd "$(dirname "$0")/Locus"

SCHEME="Locus"
BUNDLE_ID="com.locus.ios"
DERIVED="$HOME/Library/Developer/Xcode/DerivedData/LocusDevice"

# Passed on the command line rather than written into project.yml: the generated
# project stays free of a personal team id, and this covers every target in the
# build (the app and LocusUITests) without editing each one.
TEAM="${LOCUS_DEVELOPMENT_TEAM:-3924UTFR6T}"

do_launch=0
for arg in "$@"; do
  case "$arg" in
    --launch) do_launch=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Regenerate only when project.yml has moved ahead of the generated project, so a
# plain refresh doesn't churn the pbxproj and dirty the working tree.
if [ project.yml -nt Locus.xcodeproj/project.pbxproj ]; then
  echo "==> Regenerating the Xcode project"
  xcodegen generate
fi

echo "==> Looking for the phone"
# Read the JSON, not the table: the table's State column says "unavailable" for a
# paired-but-absent phone, and a substring match on that finds "available" and
# picks a device that cannot be installed to — five wasted minutes of build.
DEVICE_JSON="$(mktemp -t locus-devices)"
trap 'rm -f "$DEVICE_JSON"' EXIT
xcrun devicectl list devices --json-output "$DEVICE_JSON" >/dev/null 2>&1 || true

UDID=$(python3 - "$DEVICE_JSON" <<'PY'
import json, sys
try:
    devices = json.load(open(sys.argv[1]))["result"]["devices"]
except Exception:
    sys.exit(0)
for d in devices:
    if d.get("hardwareProperties", {}).get("platform") != "iOS":
        continue
    if d.get("connectionProperties", {}).get("tunnelState") == "unavailable":
        continue
    print(d["identifier"])
    break
PY
)

if [ -z "$UDID" ]; then
  echo
  echo "No reachable iPhone." >&2
  echo >&2
  xcrun devicectl list devices >&2 2>/dev/null || true
  echo >&2
  echo "Unlock the phone, then either plug it in or make sure it is on this wifi" >&2
  echo "with 'Connect via Network' ticked in Xcode > Window > Devices and Simulators." >&2
  exit 1
fi
echo "    $UDID"

echo "==> Building (this re-signs; the first run may ask for your keychain password)"
# -allowProvisioningUpdates is the whole point: it lets Xcode mint a fresh
# profile without the Devices window being open.
set +e
xcodebuild \
  -project Locus.xcodeproj \
  -scheme "$SCHEME" \
  -configuration Debug \
  -destination "id=$UDID" \
  -derivedDataPath "$DERIVED" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM" \
  build
BUILD_STATUS=$?
set -e

if [ $BUILD_STATUS -ne 0 ]; then
  echo >&2
  echo "Build failed. Two failures are common here:" >&2
  echo >&2
  echo "  'Failed to register bundle identifier'" >&2
  echo "      $BUNDLE_ID is taken by someone else's app. Change" >&2
  echo "      PRODUCT_BUNDLE_IDENTIFIER in ios/Locus/project.yml to something" >&2
  echo "      unique (e.g. com.sharadyadav.locus), then run this again." >&2
  echo >&2
  echo "  'No signing certificate' / 'no account for team'" >&2
  echo "      Open Xcode > Settings > Accounts and sign in once, then retry." >&2
  exit $BUILD_STATUS
fi

APP="$DERIVED/Build/Products/Debug-iphoneos/$SCHEME.app"
if [ ! -d "$APP" ]; then
  echo "Built, but $APP is missing — nothing to install." >&2
  exit 1
fi

echo "==> Installing to the phone"
# Same bundle id as the copy already there, so this installs over the top and
# the app keeps its data and its saved login.
xcrun devicectl device install app --device "$UDID" "$APP"

if [ "$do_launch" = "1" ]; then
  echo "==> Launching"
  xcrun devicectl device process launch --device "$UDID" "$BUNDLE_ID" >/dev/null
fi

echo
echo "Done. Locus is good for another 7 days (a year on a paid account)."
echo "If it refuses to open on the phone, trust the certificate once at"
echo "Settings > General > VPN & Device Management."

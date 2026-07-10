#!/usr/bin/env bash
#
# Generate the project, build the app, and run it in the iOS Simulator —
# the whole loop in one command. Run from the `ios/` directory:
#
#     ./run.sh
#
# Override the simulator with SIMULATOR, e.g. `SIMULATOR="iPhone 17 Pro" ./run.sh`.

set -euo pipefail
cd "$(dirname "$0")"

SIMULATOR="${SIMULATOR:-iPhone 17}"
BUNDLE_ID="ru.enzet.emmio"

echo "==> Generating project"
xcodegen generate

echo "==> Building for '$SIMULATOR'"
xcodebuild build \
    -project Emmio.xcodeproj -scheme Emmio \
    -destination "platform=iOS Simulator,name=$SIMULATOR" \
    -quiet CODE_SIGNING_ALLOWED=NO

# The built .app, straight from the build settings (survives DerivedData moves).
APP_PATH="$(xcodebuild -project Emmio.xcodeproj -scheme Emmio \
    -destination "platform=iOS Simulator,name=$SIMULATOR" \
    -showBuildSettings 2>/dev/null \
    | awk '/ TARGET_BUILD_DIR =/{d=$3} / FULL_PRODUCT_NAME =/{p=$3} END{print d"/"p}')"

echo "==> Booting, installing, launching"
xcrun simctl boot "$SIMULATOR" 2>/dev/null || true
open -a Simulator
xcrun simctl install "$SIMULATOR" "$APP_PATH"
xcrun simctl launch "$SIMULATOR" "$BUNDLE_ID"

echo "==> Done. Start the backend if you haven't:"
echo "    uvicorn emmio.api.app:app --reload   (from the repo root)"

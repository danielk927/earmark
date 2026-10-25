#!/bin/bash
# Builds mac/build/Earmark.app and mac/build/EarmarkSpatialSpike.app without Xcode:
# swift build -c release, hand-made bundles, Info.plist with the usage strings, signed with the
# Apple Development identity (stable TCC identity across rebuilds) under the hardened runtime.
#
# Usage:
#   mac/build_app.sh                         build and sign both apps
#   mac/build_app.sh --open app  [-- ARGS]   ...then launch Earmark.app via `open -n` (TCC attributes to the bundle)
#   mac/build_app.sh --open spike [-- ARGS]  ...then launch EarmarkSpatialSpike.app
#   mac/build_app.sh --open both [-- ARGS]
# Logs of launched apps go to logs/earmark_app.out.log and logs/spatial_spike.out.log (stdout and stderr).
# Example: mac/build_app.sh --open app -- --mock-head --no-mic
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD="$HERE/build"
OPEN=""
APP_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --open) OPEN="${2:-}"; shift 2 ;;
        --) shift; APP_ARGS=("$@"); break ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

cd "$HERE"
echo "==> swift build -c release"
swift build -c release --product SpatialSpike
swift build -c release --product EarmarkApp
BIN="$(swift build -c release --show-bin-path)"

# Signing identity: the first "Apple Development" identity; ad-hoc as a fallback.
IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | awk '/Apple Development/ { print $2; exit }')"
if [ -z "$IDENTITY" ]; then
    echo "WARNING: no Apple Development identity found; signing ad-hoc. macOS will re-ask for mic, speech," >&2
    echo "         and motion permission after every rebuild (ad-hoc signatures are cdhash-bound)." >&2
    IDENTITY="-"
else
    echo "==> signing identity: $(security find-identity -v -p codesigning | awk -v id="$IDENTITY" '$2 == id { $1=""; $2=""; print substr($0, 3) }')"
fi

mkdir -p "$BUILD"
ENTITLEMENTS="$BUILD/entitlements.plist"
cat > "$ENTITLEMENTS" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Hardened runtime: the microphone needs this (docs/sponsors/vendor-notes/apple-spatial-audio.md section 7). -->
    <key>com.apple.security.device.audio-input</key><true/>
</dict>
</plist>
PLIST
plutil -lint "$ENTITLEMENTS" >/dev/null

# make_bundle <executable> <bundle name> <bundle id> <display name>
make_bundle() {
    local exe="$1" name="$2" bid="$3" display="$4"
    local app="$BUILD/$name.app"
    echo "==> $app"
    rm -rf "$app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cp "$BIN/$exe" "$app/Contents/MacOS/$exe"
    cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>$bid</string>
    <key>CFBundleName</key><string>$display</string>
    <key>CFBundleDisplayName</key><string>$display</string>
    <key>CFBundleExecutable</key><string>$exe</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSSupportsAutomaticTermination</key><false/>
    <key>NSMicrophoneUsageDescription</key><string>Earmark listens for your voice requests, such as "Where's the sugar?", using the Mac's built-in microphone.</string>
    <key>NSSpeechRecognitionUsageDescription</key><string>Earmark transcribes your voice requests on this Mac when the online speech service is unavailable.</string>
    <key>NSMotionUsageDescription</key><string>Earmark uses AirPods head tracking so guidance sounds stay fixed in the room while you turn your head.</string>
    <key>EarmarkRepoRoot</key><string>$REPO</string>
</dict>
</plist>
PLIST
    plutil -lint "$app/Contents/Info.plist"
    if [ -d "$REPO/config/phrases" ]; then
        cp -R "$REPO/config/phrases" "$app/Contents/Resources/phrases"
        echo "    bundled $(find "$app/Contents/Resources/phrases" -name '*.wav' | wc -l | tr -d ' ') cached phrases"
    fi
    cp "$REPO/config/space.json" "$app/Contents/Resources/space.json"
    # Finder/iCloud attributes on files in Documents can appear mid-build and make signing fail, so clear and retry.
    for try in 1 2 3; do
        xattr -cr "$app"
        codesign --force --options runtime --timestamp=none --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$app" 2>&1 \
            | grep -v "replacing existing signature" || true
        codesign --verify --strict "$app" 2>/dev/null && break
        sleep 1
    done
    codesign --verify --strict --verbose=2 "$app"
}

make_bundle EarmarkApp Earmark com.earmark.app Earmark
make_bundle SpatialSpike EarmarkSpatialSpike com.earmark.spike "Earmark Spatial Spike"

launch() {
    local name="$1" log="$2"
    mkdir -p "$REPO/logs"
    : > "$REPO/logs/$log"
    echo "==> open -n $BUILD/$name.app ${APP_ARGS[*]:-} (log: logs/$log)"
    if [ ${#APP_ARGS[@]} -gt 0 ]; then
        open -n --stdout "$REPO/logs/$log" --stderr "$REPO/logs/$log" "$BUILD/$name.app" --args "${APP_ARGS[@]}"
    else
        open -n --stdout "$REPO/logs/$log" --stderr "$REPO/logs/$log" "$BUILD/$name.app"
    fi
}

case "$OPEN" in
    "") ;;
    app) launch Earmark earmark_app.out.log ;;
    spike) launch EarmarkSpatialSpike spatial_spike.out.log ;;
    both) launch Earmark earmark_app.out.log; launch EarmarkSpatialSpike spatial_spike.out.log ;;
    *) echo "--open takes app, spike, or both" >&2; exit 2 ;;
esac
echo "==> done"

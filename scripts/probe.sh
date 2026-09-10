#!/bin/sh
# Probe a Netatmo Presence's local API and report what the firmware answers.
#
# Only GET requests are made, and only to endpoints that read state -- nothing
# here changes the camera's configuration. `changestatus` is probed without its
# `status` parameter precisely so it cannot toggle monitoring.
#
# The device key is redacted from the output, so the report can be shared.
#
# Usage:
#   ./scripts/probe.sh camera-parking.home "$SECRET"
#   ./scripts/probe.sh camera-parking.home "$SECRET" get_zones another_command

set -u

if [ $# -lt 2 ]; then
    echo "usage: $0 <host> <device-key> [extra-command ...]" >&2
    exit 2
fi

HOST=$1
KEY=$2
shift 2

case "$HOST" in
    http://*|https://*) BASE=$HOST ;;
    *) BASE="http://$HOST" ;;
esac
BASE=${BASE%/}

TIMEOUT=${TIMEOUT:-5}
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT

# Commands worth trying, beyond the ones the integration already relies on.
# Some only route when their parameters are present -- a bare
# `get_events_until` 404s on firmwares that do implement it -- so the query
# string is part of the candidate.
#
# `changestatus` is deliberately absent: it only routes with its `status`
# parameter, and supplying one would switch monitoring. Test it by hand if you
# need to know, with `status=on`, which never turns a camera off.
COMMANDS="ping
get_config
get_status
getmodulestatus
floodlight_get_config
get_light_config
get_events_until?offset=1
get_events?offset=1
sd_status
sdcard_status
get_ftp_config
get_timelapse_config
get_zone_config
get_zones
get_notification_config
get_detection_config"

PATHS="live/snapshot_720.jpg
live/index_local.m3u8
live/index.m3u8
live/files/high/index.m3u8
live/files/medium/index.m3u8"

# Report one endpoint: status, content type, size, and a short body preview
# with the device key blanked out.
probe() {
    url=$1
    label=$2
    meta=$(curl -s -m "$TIMEOUT" -o "$BODY" \
        -w '%{http_code} %{content_type} %{size_download}' "$url" 2>/dev/null)

    if [ -z "$meta" ]; then
        printf '%-38s -- unreachable\n' "$label"
        return 1
    fi

    code=${meta%% *}
    rest=${meta#* }
    ctype=${rest%% *}
    size=${rest##* }

    case "$ctype" in
        image/*|video/*|application/octet-stream)
            preview="<$size bytes of binary>"
            ;;
        *)
            preview=$(tr -d '\r\n' < "$BODY" | cut -c1-300 | sed "s|$KEY|<KEY>|g")
            ;;
    esac

    printf '%-38s %s %-28s %s\n' "$label" "$code" "$ctype" "$preview"
    [ "$code" != "404" ]
}

echo "# Netatmo Presence local API probe -- $HOST"
echo
echo "## Unauthenticated"
probe "$BASE/command/ping" "command/ping" || true

echo
echo "## Commands"
supported=""
for cmd in $COMMANDS "$@"; do
    if probe "$BASE/$KEY/command/$cmd" "command/$cmd"; then
        supported="$supported command/$cmd"
    fi
done

echo
echo "## Media paths"
for p in $PATHS; do
    if probe "$BASE/$KEY/$p" "$p"; then
        supported="$supported $p"
    fi
done

echo
echo "## Summary"
for endpoint in $supported; do
    echo "  - $endpoint"
done

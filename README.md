# Netatmo Presence — local Home Assistant integration

[![CI](https://github.com/thecampagnards/netatmo-presence-local/actions/workflows/ci.yml/badge.svg)](https://github.com/thecampagnards/netatmo-presence-local/actions/workflows/ci.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

Control a **Netatmo Presence** (Smart Outdoor Camera) straight over the local
network, through the HTTP API embedded in the camera. No Netatmo account, no
cloud round-trip, no token to refresh: Home Assistant talks to the camera
directly.

```console
$ curl http://camera-parking.home/$SECRET/command/floodlight_get_config
{"intensity":100,"mode":"auto","night":{"always":false,"person":true,"vehicle":true,"animal":false,"movement":false}}
```

## Installation

### Through HACS (recommended)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thecampagnards&repository=netatmo-presence-local&category=integration)

If the button does not open, add the repository by hand: **HACS → Integrations
→ ⋮ → Custom repositories**, URL
`https://github.com/thecampagnards/netatmo-presence-local`, category
`Integration`. Install it, then restart Home Assistant.

### Manually

Copy `custom_components/netatmo_presence_local` into the `custom_components`
folder of your configuration, then restart Home Assistant.

### Setup

[![Add the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=netatmo_presence_local)

**Settings → Devices & services → Add integration → Netatmo Presence
(local)**, then fill in:

| Field | Example | Description |
| --- | --- | --- |
| Host | `camera-parking.home` | Hostname or IP of the camera, without `http://` |
| Device key | `abcdef0123456789…` | The secret segment of the local URL |

The user interface ships in English and French; Home Assistant picks whichever
matches your profile language.

### Changing the address or the key later

**Settings → Devices & services → Netatmo Presence (local) → ⋮ → Reconfigure**
lets you point the entry at a new address, a new device key, or both, without
removing and re-adding the integration — entity IDs, history and automations
are kept.

If the camera reports its MAC (through `get_config`), the new settings are
checked against it and a mismatch is refused, so you cannot silently retarget
an entry at a different camera. Firmwares that do not expose `get_config`
identify the entry by its host instead, so changing the address there is
simply accepted.

When only the key is wrong, Home Assistant notices on its own and asks for a
new one through a repair notification; you do not need the reconfigure form
for that.

## Finding the device key

Every local command lives under a secret URL segment, specific to your camera:

```
http://<camera-ip>/<device-key>/command/ping
```

Three ways to get hold of it:

- **From the Netatmo Security app**, in the camera settings: the local access
  URL contains the key.
- **From the Netatmo API**, via [dev.netatmo.com](https://dev.netatmo.com):
  `GET /api/gethomedata` returns a `vpn_url` shaped like
  `https://.../restricted/10.x.x.x/<device-key>/...`.
- **If you already have it** somewhere in your scripts (`$SECRET` in a `curl`
  call), that is exactly the value.

The key is a secret: it grants full access to the camera on the LAN. This
integration never writes it to the logs or to its diagnostics output.

## Feature discovery

Netatmo firmwares do not all expose the same commands. On startup the
integration **probes the camera** and only creates entities backed by an
endpoint that actually answers. A firmware without `get_events_until` simply
gets no event sensors — no error, no unavailable entity.

Probing is read-only. `changestatus` in particular is queried *without* its
`status` parameter, precisely so it cannot toggle monitoring.

After a firmware update, the **Re-detect features** button runs the probe
again.

### What one Presence actually exposed

Verified against a Netatmo Presence on firmware reporting `product_name: noc`:

| Endpoint | Result |
| --- | --- |
| `command/ping` | ✅ `{"local_url": "...", "product_name": "noc"}` |
| `command/floodlight_get_config` | ✅ the full floodlight configuration |
| `command/changestatus?status=on` | ✅ answers `409 {"code": 7, "Already on"}` |
| `live/snapshot_720.jpg` | ✅ ~240 kB JPEG |
| `live/index.m3u8` | ✅ HLS playlist |
| `live/index_local.m3u8` | ❌ absent |
| `command/get_config` and every config variant tried | ❌ absent |
| `command/get_events_until` (with or without parameters) | ❌ absent |

So on that firmware you get the floodlight, the camera and the monitoring
switch — no event sensors and no diagnostic sensors, because nothing reports
them. Two behaviours worth knowing about, both handled:

- **Unknown routes return the web server's HTML error page**, not a JSON
  error. Any HTML body is therefore read as "command absent", including under
  an HTTP 200.
- **`changestatus` only routes when `status` is present**, so it cannot be
  probed without switching monitoring. It is part of the documented command
  set and is taken as available once any other command answered. Since a
  firmware without `get_config` cannot report monitoring back, that switch
  shows an assumed state: Home Assistant offers explicit on/off buttons, and
  the state is tracked from the commands sent.

To see what your camera exposes without going through Home Assistant, use
either probe script — they take the same arguments and print the same report:

```console
$ python3 scripts/probe.py camera-parking.home "$SECRET"   # needs Python 3
$ sh scripts/probe.sh camera-parking.home "$SECRET"        # needs curl only
```

Neither writes anything to the camera, and both blank the device key out of
their output, so the report is safe to paste into an issue. Pass extra command
names as trailing arguments to probe endpoints that are not in the built-in
list.

## Entities

### Floodlight

| Entity | Type | Purpose |
| --- | --- | --- |
| Floodlight | `light` | Forced-on state and brightness |
| Floodlight mode | `select` | `on` / `off` / `auto` |
| Floodlight intensity | `number` | 0 to 100 % |
| Night light always on | `switch` | `night.always` |
| Night light on person | `switch` | `night.person` |
| Night light on vehicle | `switch` | `night.vehicle` |
| Night light on animal | `switch` | `night.animal` |
| Night light on movement | `switch` | `night.movement` |

`light.is_on` reflects the **configured** mode, not the physical lamp: in
`auto` the camera decides on its own and reports no feedback, so the entity is
considered off until the mode is forced to `on`.

**Turning the light off restores the mode it was resting in.** An automatic
floodlight switched on and then off again goes back to `auto`, rather than
ending up disabled. The resting mode is tracked on every poll, so it works
however the light came to be on — this integration, the mode selector, or the
Netatmo app. The `restores_to` attribute shows where the light will land. The
only case that falls back to plain `off` is Home Assistant starting up with
the light already forced on, where no resting mode was ever observed.

The night switches choose what turns the floodlight on after dark while it is
in automatic mode.

### Camera and monitoring

| Entity | Type | Purpose |
| --- | --- | --- |
| *(device name)* | `camera` | Still image and local HLS stream |
| Monitoring | `switch` | Enables or disables video monitoring |

### Events and diagnostics

| Entity | Type | Purpose |
| --- | --- | --- |
| Motion / Person / Vehicle / Animal | `binary_sensor` | Recent detection |
| Last event | `sensor` | Timestamp, details in attributes |
| Last event type | `sensor` | `human`, `vehicle`, … |
| SD card, power, firmware, Wi-Fi status | `sensor` | Diagnostics |

Detection sensors read the camera's event log every 30 seconds and stay on for
90 seconds after an event. For real-time detection, keep the webhooks of the
official Netatmo integration: this component targets local control, not
latency.

## Timing

There are three different delays, and only one of them is avoidable:

| What | Delay |
| --- | --- |
| A change you make from Home Assistant | none — applied locally as soon as the camera accepts it |
| A change made elsewhere (Netatmo app, another client) | up to 30 seconds, the polling interval |
| A detection appearing on a `binary_sensor` | up to 30 seconds, then it stays on for 90 |

Commands do not wait for a re-read: the camera echoes back exactly the
configuration it was handed, so the answer is already known and is applied
straight away. The regular poll then confirms it.

One delay no amount of polling fixes: in `auto` mode the camera never reports
whether the lamp is physically lit, only the configured mode. Same for
monitoring on firmwares without `get_config` — the switch shows the state this
integration last set, not one read back from the camera.

## Services

### `netatmo_presence_local.set_floodlight`

Sets the mode and the intensity in a single call.

```yaml
action: netatmo_presence_local.set_floodlight
target:
  entity_id: light.parking_floodlight
data:
  mode: auto
  intensity: 80
```

### `netatmo_presence_local.set_night_triggers`

Chooses which night-time detections switch the floodlight on.

```yaml
action: netatmo_presence_local.set_night_triggers
target:
  entity_id: light.parking_floodlight
data:
  person: true
  vehicle: true
  animal: false
```

Omitted fields keep their value: the integration reads the current
configuration back and applies only your change to it.

### `netatmo_presence_local.raw_command`

Calls any command of the local API and returns its response. Useful to explore
an endpoint specific to your firmware.

```yaml
action: netatmo_presence_local.raw_command
data:
  device_id: 1234567890abcdef
  command: get_events_until
  params:
    offset: "5"
response_variable: answer
```

## Example automation

Light up at full power when a person is detected after dark, then fall back to
automatic:

```yaml
automation:
  - alias: Floodlight full power on person
    triggers:
      - trigger: state
        entity_id: binary_sensor.parking_person
        to: "on"
    conditions:
      - condition: sun
        after: sunset
    actions:
      - action: netatmo_presence_local.set_floodlight
        target:
          entity_id: light.parking_floodlight
        data:
          mode: "on"
          intensity: 100
      - delay: "00:02:00"
      - action: netatmo_presence_local.set_floodlight
        target:
          entity_id: light.parking_floodlight
        data:
          mode: auto
```

## Local API

The endpoints in use, all `GET`:

| Path | Purpose |
| --- | --- |
| `/command/ping` | Camera identity (also served under the key) |
| `/<key>/command/floodlight_get_config` | Reads `{intensity, mode, night}` |
| `/<key>/command/floodlight_set_config?config=<json>` | Writes the floodlight configuration |
| `/<key>/command/changestatus?status=on\|off` | Video monitoring; `409` code `7` means it was already in that state |
| `/<key>/command/get_config` | Module configuration |
| `/<key>/command/get_events_until?offset=<n>` | Event log |
| `/<key>/live/snapshot_720.jpg` | Still image |
| `/<key>/live/index_local.m3u8`, `/<key>/live/index.m3u8` | HLS stream |

`floodlight_set_config` replaces the whole object. The integration therefore
always reads the current configuration back and merges your change into it —
key by key inside the `night` sub-object — before writing.

## Development

```console
$ python3 -m unittest discover -s tests -t tests -v
```

The suite depends on the standard library only: it stubs `aiohttp` and drives
the client against an HTTP server that mimics the camera, so it runs without a
Home Assistant install.

Linting is handled by [Ruff](https://docs.astral.sh/ruff/), configured in
`pyproject.toml` and enforced by CI:

```console
$ ruff check --fix . && ruff format .
```

CI also runs [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest)
and the HACS validation action. Two of the HACS checks are settings on the
GitHub repository rather than files in it: it must have a **description** and
at least one **topic**.

## Known limitations

- The floodlight's `auto` mode does not report the lamp's real state; only the
  configured mode is observable.
- Detection goes through polling: expect up to 30 seconds of latency, and
  only on firmwares that implement `get_events_until` — several do not.
- Monitoring cannot be read back without `get_config`; its switch then shows
  an assumed state.
- Available commands vary by firmware; run `scripts/probe.py` to see what
  yours exposes.

## Credits

The floodlight and `changestatus` endpoints are documented in [Sascha Curth's
Netatmo Presence
compendium](https://github.com/scurth/blog_sascha-curth.de/blob/master/kompendium/005_Netatmo_Presence.md).

The brand assets in `custom_components/netatmo_presence_local/brand/` are
Netatmo's, reused to identify the hardware this integration drives — the same
images Home Assistant ships for its built-in `netatmo` integration. Refresh
them with `python3 scripts/fetch_brand_icon.py`.

Released under the MIT licence. Not affiliated with, or endorsed by, Netatmo /
Legrand.

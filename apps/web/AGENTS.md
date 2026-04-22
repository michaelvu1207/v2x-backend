# Web Dashboard — Agent Notes

SvelteKit 2 + Vite 6 + TypeScript + Tailwind 4. Static site, deployed via Amplify.
Frontend connects to the bridge over WebSocket (`:8765`) and to the read API over HTTPS.

## Driving input: wheel, pedals, and keyboard

The browser reads the wheel/pedals via the Gamepad API, normalizes them through a
calibration layer, and pushes `{ steer, throttle, brake, reverse, handbrake }` to
the bridge every tick over WebSocket. Geo translation lives in the bridge, not here
— the frontend only ships normalized control values.

### File tree (driving logic)

```
apps/web/src/
├── lib/
│   ├── stores/
│   │   ├── gamepad.ts            ★ wheel/pedal reading + calibration state
│   │   ├── keyboard.ts           ★ keyboard fallback controls (WASD)
│   │   └── driveSocket.ts        ★ sends control packets to bridge (WS)
│   ├── components/
│   │   ├── CalibrationWizard.svelte  ★ UI for auto-detecting axes
│   │   ├── HudOverlay.svelte         displays live steer/throttle/brake
│   │   └── DriveMiniMap.svelte
│   ├── types.ts                  GamepadCalibration, DriveControl types
│   └── constants.ts              deadzones, poll rates, LS keys
└── routes/drive/
    ├── +page.ts
    └── +page.svelte              ★ wires gamepad → driveSocket each frame
```

### Primary files to edit

**`lib/stores/gamepad.ts`** — the core. Reads `navigator.getGamepads()`, applies
the persisted `GamepadCalibration` (localStorage key `drive_calibration_v4`:
axis indices, inversion flags, per-pedal min/max), and exposes derived Svelte
stores consumed by the rest of the UI. Edit here for: steer curves, pedal
response curves, deadzone math, adding a clutch / H-shifter, schema changes.

**`lib/stores/keyboard.ts`** — WASD fallback. Mirror its pattern when adding new
input sources. Edit here for: key bindings, keyboard-only tuning, mix logic
with the wheel.

**`lib/components/CalibrationWizard.svelte`** — UI flow that captures raw axis
min/max while the user presses each pedal and turns the wheel lock-to-lock,
then writes into the gamepad store's calibration. Edit here for: new
calibration steps, sensitivity sliders, exposing curve params.

**`lib/stores/driveSocket.ts`** — WebSocket transport to the bridge. Sends the
`control` message at a fixed tick rate, plus `place_v2x_signal`,
`sync_v2x_zones`, session messages. Edit here for: message shape/rate, new
control fields, smoothing before send.

**`routes/drive/+page.svelte`** — composition. Mounts the gamepad poll loop,
subscribes to the gamepad store, forwards values into `driveSocket.sendControl`
per animation frame, hosts CalibrationWizard + HUD. Edit here for: when/how
controls are sent, keyboard+wheel blending, adding a "calibrate" button.

### Supporting

- `lib/types.ts` — `GamepadCalibration`, control message interfaces. Keep in
  sync with schema changes in `gamepad.ts` and the bridge's `drive_server.py`.
- `lib/constants.ts` — deadzone values, poll interval, localStorage key name.
  **Bump the LS key** (e.g. `_v4` → `_v5`) whenever the calibration struct
  changes shape, so stale saved calibrations don't get mis-parsed.

### Typical edit flows

- **Tuning feel** → `gamepad.ts` (curves / deadzone).
- **New UI knob** → `CalibrationWizard.svelte` + `gamepad.ts` (extend struct +
  bump LS key) + `types.ts`.
- **New control channel (e.g. clutch)** → `types.ts` + `gamepad.ts` +
  `driveSocket.ts` + matching handler in bridge `drive_server.py`.
- **Keyboard-only change** → `keyboard.ts` (and possibly `+page.svelte` for
  wiring).

### Gotchas

- Geo calibration for V2X detections is **not** in the frontend — see
  `apps/bridge/digital_twin_bridge/geo_utils.py` (`gps_to_carla`). The only
  "calibration" on the web side is input-device calibration.
- Zones drawn on the map are sent as `[lon, lat][]` polygons; the bridge
  converts them per-vertex. Don't pre-translate to CARLA coords on the client.
- The drive page only runs when `/drive` is focused; background tabs throttle
  `requestAnimationFrame`, which starves the control tick. Keep the tab active
  when testing.

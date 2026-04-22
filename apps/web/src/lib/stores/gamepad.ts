/**
 * Gamepad Store — steering wheel + pedal input via the browser Gamepad API.
 *
 * Pedal normalization strategy:
 *   The G923's pedal axes swing between -1 and +1, but the rest position
 *   can be either end and varies between sessions. Instead of guessing the
 *   rest value from an unreliable initial snapshot, we:
 *
 *   1. Output zeros until we're confident about the mapping.
 *   2. On each poll frame, track the min and max values seen per pedal axis.
 *   3. Once we've seen a full-range sweep (max - min > 1.0), the pedal has
 *      been pressed and released. At that point, the current value is at rest.
 *   4. Fallback: if 120 frames (~2s) pass without a sweep, snapshot whatever
 *      extreme the axis is at now (driver should have stabilized by then).
 *
 * Only axis assignments are persisted to localStorage. Inversion is always
 * re-detected at runtime.
 */

import { writable, derived, get } from 'svelte/store';
import { GAMEPAD_DEADZONE, DEFAULT_CALIBRATION } from '$lib/constants';
import type { GamepadCalibration } from '$lib/types';

// ── Public Stores ──

export const gamepadConnected = writable<boolean>(false);
export const gamepadName = writable<string>('');
export const gamepadIndex = writable<number>(-1);
export const rawAxes = writable<number[]>([]);
export const rawButtons = writable<boolean[]>([]);

// ── Calibration (persisted) ──
//
// Defaults in DEFAULT_CALIBRATION work for the Logitech G923 out of the box.
// localStorage only stores axis/button remappings when the wizard is used to
// override defaults for different hardware.

const STORAGE_KEY = 'drive_calibration_v5';

function loadCalibration(): GamepadCalibration {
	if (typeof localStorage === 'undefined') return DEFAULT_CALIBRATION;
	const saved = localStorage.getItem(STORAGE_KEY);
	if (!saved) return DEFAULT_CALIBRATION;
	try {
		const axes = JSON.parse(saved);
		return {
			...DEFAULT_CALIBRATION,
			steerAxis: axes.steerAxis ?? DEFAULT_CALIBRATION.steerAxis,
			gasAxis: axes.gasAxis ?? DEFAULT_CALIBRATION.gasAxis,
			brakeAxis: axes.brakeAxis ?? DEFAULT_CALIBRATION.brakeAxis,
			reverseButton: axes.reverseButton ?? DEFAULT_CALIBRATION.reverseButton,
		};
	} catch {
		return DEFAULT_CALIBRATION;
	}
}

export const calibration = writable<GamepadCalibration>(loadCalibration());

calibration.subscribe((cal) => {
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem(STORAGE_KEY, JSON.stringify({
			steerAxis: cal.steerAxis,
			gasAxis: cal.gasAxis,
			brakeAxis: cal.brakeAxis,
			reverseButton: cal.reverseButton,
		}));
	}
});

// ── Pedal Detection State ──

interface PedalTracker {
	min: number;
	max: number;
	rest: number;
	detected: boolean;
}

let gas: PedalTracker = { min: Infinity, max: -Infinity, rest: 0, detected: false };
let brake: PedalTracker = { min: Infinity, max: -Infinity, rest: 0, detected: false };
let framesPolled = 0;

// ── Reverse Gear State ──
//
// Mirrors the CARLA manual_control_steeringwheel.py pattern: a dedicated
// wheel button toggles reverse on rising-edge. Each poll we compare the
// current pressed state of the calibrated reverseButton to the previous
// frame; a false→true transition flips `reverseState`.
export const reverseState = writable<boolean>(false);
let prevReverseButtonPressed = false;

export function toggleReverse(): void {
	reverseState.update((r) => !r);
}

export function setReverse(value: boolean): void {
	reverseState.set(value);
}

const SWEEP_THRESHOLD = 1.0;   // min-max range that confirms a full press+release
const FALLBACK_FRAMES = 120;   // ~2s: if no sweep seen, snapshot current value

function resetDetection(): void {
	gas = { min: Infinity, max: -Infinity, rest: 0, detected: false };
	brake = { min: Infinity, max: -Infinity, rest: 0, detected: false };
	framesPolled = 0;
	prevReverseButtonPressed = false;
	reverseState.set(false);
}

function isAtExtreme(value: number): boolean {
	return Math.abs(value) > 0.85;
}

function updateTracker(tracker: PedalTracker, raw: number, frames: number): void {
	if (tracker.detected) return;

	tracker.min = Math.min(tracker.min, raw);
	tracker.max = Math.max(tracker.max, raw);
	const hasSweep = tracker.max - tracker.min > SWEEP_THRESHOLD;

	// Primary: full sweep seen AND pedal has returned to an extreme (rest).
	// This avoids capturing a mid-transit value as rest.
	if (hasSweep && isAtExtreme(raw)) {
		tracker.rest = raw;
		tracker.detected = true;
		return;
	}

	// Fallback: after 2 seconds with no sweep, use current extreme value.
	if (!hasSweep && frames >= FALLBACK_FRAMES && isAtExtreme(raw)) {
		tracker.rest = raw;
		tracker.detected = true;
		return;
	}
}

// ── Normalization ──

export interface NormalizedInput {
	steer: number;    // -1 (left) to 1 (right)
	throttle: number; // 0 to 1
	brake: number;    // 0 to 1
	reverse: boolean;
}

/**
 * Normalize a pedal axis to 0 (released) → 1 (pressed).
 * Rest is auto-detected at runtime and is always at an axis extreme (±1).
 */
function normalizePedal(raw: number, rest: number): number {
	if (rest > 0) {
		// Rest at +1 → pressed goes toward -1
		return Math.max(0, Math.min(1, (1 - raw) / 2));
	}
	// Rest at -1 → pressed goes toward +1
	return Math.max(0, Math.min(1, (raw + 1) / 2));
}

export const normalizedInput = derived(
	[rawAxes, calibration, reverseState],
	([$rawAxes, $cal, $reverse]): NormalizedInput => {
		if ($rawAxes.length === 0 || !gas.detected) {
			return { steer: 0, throttle: 0, brake: 0, reverse: $reverse };
		}

		// Steering (always works — no rest ambiguity)
		let steer = $cal.steerInverted
			? -($rawAxes[$cal.steerAxis] ?? 0)
			: ($rawAxes[$cal.steerAxis] ?? 0);
		if (Math.abs(steer) < GAMEPAD_DEADZONE) steer = 0;
		steer = Math.max(-1, Math.min(1, steer));

		// Pedals
		let throttle = normalizePedal($rawAxes[$cal.gasAxis] ?? 0, gas.rest);
		let brakeVal = brake.detected
			? normalizePedal($rawAxes[$cal.brakeAxis] ?? 0, brake.rest)
			: 0;
		if (throttle < GAMEPAD_DEADZONE) throttle = 0;
		if (brakeVal < GAMEPAD_DEADZONE) brakeVal = 0;

		return { steer, throttle, brake: brakeVal, reverse: $reverse };
	}
);

// ── Polling ──

let animFrameId: number | null = null;

function poll() {
	const gp = navigator.getGamepads()[get(gamepadIndex)];
	if (!gp) {
		if (get(gamepadIndex) >= 0) gamepadConnected.set(false);
		animFrameId = requestAnimationFrame(poll);
		return;
	}

	rawAxes.set([...gp.axes]);
	rawButtons.set(gp.buttons.map((b) => b.pressed));

	// Reverse-gear toggle: rising-edge on calibrated button flips state.
	// Mirrors CARLA's manual_control_steeringwheel.py where the reverse
	// button sets gear = 1 if currently in reverse else -1.
	const cal = get(calibration);
	const revIdx = cal.reverseButton;
	if (revIdx >= 0 && revIdx < gp.buttons.length) {
		const pressed = gp.buttons[revIdx].pressed;
		if (pressed && !prevReverseButtonPressed) {
			reverseState.update((r) => !r);
		}
		prevReverseButtonPressed = pressed;
	} else {
		prevReverseButtonPressed = false;
	}

	// Update pedal detection
	if (!gas.detected || !brake.detected) {
		framesPolled++;
		updateTracker(gas, gp.axes[cal.gasAxis] ?? 0, framesPolled);
		updateTracker(brake, gp.axes[cal.brakeAxis] ?? 0, framesPolled);
	}

	animFrameId = requestAnimationFrame(poll);
}

// ── Lifecycle ──

export function startPolling(): void {
	if (animFrameId !== null) return;

	window.addEventListener('gamepadconnected', onConnect);
	window.addEventListener('gamepaddisconnected', onDisconnect);

	for (const gp of navigator.getGamepads()) {
		if (gp) {
			gamepadIndex.set(gp.index);
			gamepadConnected.set(true);
			gamepadName.set(gp.id);
			resetDetection();
			break;
		}
	}

	animFrameId = requestAnimationFrame(poll);
}

export function stopPolling(): void {
	if (animFrameId !== null) {
		cancelAnimationFrame(animFrameId);
		animFrameId = null;
	}
	window.removeEventListener('gamepadconnected', onConnect);
	window.removeEventListener('gamepaddisconnected', onDisconnect);
}

/**
 * Re-detect pedal rest values. Called after the calibration wizard
 * reassigns axes. User should have feet off pedals.
 */
export function recalibrateRestValues(): void {
	resetDetection();
}

// ── Event Handlers ──

function onConnect(e: GamepadEvent) {
	gamepadIndex.set(e.gamepad.index);
	gamepadConnected.set(true);
	gamepadName.set(e.gamepad.id);
	console.log(`[Gamepad] Connected: ${e.gamepad.id} (${e.gamepad.axes.length} axes, ${e.gamepad.buttons.length} buttons)`);
	resetDetection();
}

function onDisconnect(e: GamepadEvent) {
	if (e.gamepad.index === get(gamepadIndex)) {
		gamepadIndex.set(-1);
		gamepadConnected.set(false);
		gamepadName.set('');
		rawAxes.set([]);
		rawButtons.set([]);
		resetDetection();
		console.log(`[Gamepad] Disconnected: ${e.gamepad.id}`);
	}
}

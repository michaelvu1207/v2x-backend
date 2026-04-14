/**
 * Gamepad Store — polls the browser Gamepad API for steering wheel input.
 *
 * Handles: connection detection, axis calibration, normalization,
 * deadzone filtering, and localStorage persistence of calibration.
 */

import { writable, derived, get } from 'svelte/store';
import { GAMEPAD_DEADZONE, DEFAULT_CALIBRATION } from '$lib/constants';
import type { GamepadCalibration } from '$lib/types';

// ── Stores ──

export const gamepadConnected = writable<boolean>(false);
export const gamepadName = writable<string>('');
export const gamepadIndex = writable<number>(-1);
export const rawAxes = writable<number[]>([]);
export const rawButtons = writable<boolean[]>([]);

// Calibration — loaded from localStorage or defaults
function loadCalibration(): GamepadCalibration {
	if (typeof localStorage === 'undefined') return DEFAULT_CALIBRATION;
	localStorage.removeItem('drive_calibration');
	const saved = localStorage.getItem('drive_calibration_v2');
	if (saved) {
		try {
			return JSON.parse(saved);
		} catch {
			return DEFAULT_CALIBRATION;
		}
	}
	return DEFAULT_CALIBRATION;
}

export const calibration = writable<GamepadCalibration>(loadCalibration());

// Auto-save calibration changes to localStorage
calibration.subscribe((cal) => {
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem('drive_calibration_v2', JSON.stringify(cal));
	}
});

// ── Normalized Input (derived) ──

export interface NormalizedInput {
	steer: number; // -1 (left) to 1 (right)
	throttle: number; // 0 to 1
	brake: number; // 0 to 1
	reverse: boolean;
}

// Pedal rest values detected on connect — used for normalization
let gasRestValue = 0;
let brakeRestValue = 0;

/**
 * Normalize a pedal axis value to 0 (released) → 1 (pressed).
 * Handles three pedal ranges based on the detected resting value:
 *   rest ≈ 0  → range is 0..1, use raw directly
 *   rest ≈ -1 → range is -1..1, use (raw + 1) / 2
 *   rest ≈ +1 → range is 1..-1, use (1 - raw) / 2
 */
function normalizePedal(raw: number, inverted: boolean, restValue: number): number {
	let value: number;
	if (Math.abs(restValue) < 0.3) {
		// Pedal rests near 0 → 0..1 range, use raw directly
		value = raw;
	} else if (inverted) {
		// Pedal rests near +1 → 1..-1 range
		value = (1 - raw) / 2;
	} else {
		// Pedal rests near -1 → -1..1 range
		value = (raw + 1) / 2;
	}
	return Math.max(0, Math.min(1, value));
}

export const normalizedInput = derived(
	[rawAxes, calibration],
	([$rawAxes, $calibration]): NormalizedInput => {
		if ($rawAxes.length === 0) {
			return { steer: 0, throttle: 0, brake: 0, reverse: false };
		}

		const rawSteer = $rawAxes[$calibration.steerAxis] ?? 0;
		const rawGas = $rawAxes[$calibration.gasAxis] ?? 0;
		const rawBrake = $rawAxes[$calibration.brakeAxis] ?? 0;

		// Steer: -1 to 1, apply deadzone
		let steer = $calibration.steerInverted ? -rawSteer : rawSteer;
		if (Math.abs(steer) < GAMEPAD_DEADZONE) steer = 0;
		steer = Math.max(-1, Math.min(1, steer));

		// Normalize pedals to 0 (released) → 1 (pressed)
		let throttle = normalizePedal(rawGas, $calibration.gasInverted, gasRestValue);
		let brake = normalizePedal(rawBrake, $calibration.brakeInverted, brakeRestValue);

		if (throttle < GAMEPAD_DEADZONE) throttle = 0;
		if (brake < GAMEPAD_DEADZONE) brake = 0;

		return { steer, throttle, brake, reverse: false };
	}
);

// ── Polling ──

let animFrameId: number | null = null;

function poll() {
	const gamepads = navigator.getGamepads();
	const idx = get(gamepadIndex);
	if (idx < 0) {
		animFrameId = requestAnimationFrame(poll);
		return;
	}

	const gp = gamepads[idx];
	if (!gp) {
		gamepadConnected.set(false);
		animFrameId = requestAnimationFrame(poll);
		return;
	}

	rawAxes.set([...gp.axes]);
	rawButtons.set(gp.buttons.map((b) => b.pressed));

	animFrameId = requestAnimationFrame(poll);
}

export function startPolling(): void {
	if (animFrameId !== null) return;

	// Listen for gamepad connections
	window.addEventListener('gamepadconnected', onGamepadConnected);
	window.addEventListener('gamepaddisconnected', onGamepadDisconnected);

	// Check if already connected
	const gamepads = navigator.getGamepads();
	for (let i = 0; i < gamepads.length; i++) {
		if (gamepads[i]) {
			gamepadIndex.set(i);
			gamepadConnected.set(true);
			gamepadName.set(gamepads[i]!.id);
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
	window.removeEventListener('gamepadconnected', onGamepadConnected);
	window.removeEventListener('gamepaddisconnected', onGamepadDisconnected);
}

function onGamepadConnected(e: GamepadEvent) {
	gamepadIndex.set(e.gamepad.index);
	gamepadConnected.set(true);
	gamepadName.set(e.gamepad.id);

	// Log all axis resting values for debugging
	const axes = [...e.gamepad.axes];
	console.log(`[Gamepad] Connected: ${e.gamepad.id} (${e.gamepad.axes.length} axes, ${e.gamepad.buttons.length} buttons)`);
	console.log(`[Gamepad] Resting axis values:`, axes.map((v, i) => `${i}=${v.toFixed(3)}`).join(', '));

	// Auto-detect pedal range from resting values
	const cal = get(calibration);
	gasRestValue = axes[cal.gasAxis] ?? 0;
	brakeRestValue = axes[cal.brakeAxis] ?? 0;

	// Detect inversion based on resting position:
	//   rest ≈ +1.0 → pedal goes 1 to -1 → needs inversion
	//   rest ≈ -1.0 → pedal goes -1 to 1 → no inversion
	//   rest ≈  0.0 → pedal goes 0 to 1  → no inversion (raw works directly)
	const gasNeedsInvert = gasRestValue > 0.5;
	const brakeNeedsInvert = brakeRestValue > 0.5;

	// For pedals that rest at 0 (0..1 range), neither formula is right.
	// We need to detect this and just use raw value.
	const gasIs01Range = Math.abs(gasRestValue) < 0.3;
	const brakeIs01Range = Math.abs(brakeRestValue) < 0.3;

	console.log(`[Gamepad] Pedal analysis: gas rest=${gasRestValue.toFixed(3)} (${gasIs01Range ? '0-1 range' : gasNeedsInvert ? '1→-1 range' : '-1→1 range'}), brake rest=${brakeRestValue.toFixed(3)} (${brakeIs01Range ? '0-1 range' : brakeNeedsInvert ? '1→-1 range' : '-1→1 range'})`);

	calibration.set({
		...cal,
		gasInverted: gasNeedsInvert,
		brakeInverted: brakeNeedsInvert,
	});
}

/**
 * Re-snapshot pedal rest values and re-detect inversion for the *current*
 * gasAxis / brakeAxis in the calibration store. Call this after the wizard
 * reassigns pedal axes — otherwise gasRestValue/brakeRestValue still refer
 * to the axes that were active at connect time, and normalizePedal will
 * misbehave. The user must have their feet OFF the pedals when this runs.
 */
export function recalibrateRestValues(): void {
	const idx = get(gamepadIndex);
	if (idx < 0) return;
	const gp = navigator.getGamepads()[idx];
	if (!gp) return;

	const cal = get(calibration);
	gasRestValue = gp.axes[cal.gasAxis] ?? 0;
	brakeRestValue = gp.axes[cal.brakeAxis] ?? 0;

	const gasNeedsInvert = gasRestValue > 0.5;
	const brakeNeedsInvert = brakeRestValue > 0.5;

	calibration.update((c) => ({
		...c,
		gasInverted: gasNeedsInvert,
		brakeInverted: brakeNeedsInvert,
	}));

	console.log(`[Gamepad] Recalibrated rest values: gas=${gasRestValue.toFixed(3)} (inverted=${gasNeedsInvert}), brake=${brakeRestValue.toFixed(3)} (inverted=${brakeNeedsInvert})`);
}

function onGamepadDisconnected(e: GamepadEvent) {
	if (e.gamepad.index === get(gamepadIndex)) {
		gamepadIndex.set(-1);
		gamepadConnected.set(false);
		gamepadName.set('');
		rawAxes.set([]);
		rawButtons.set([]);
		console.log(`[Gamepad] Disconnected: ${e.gamepad.id}`);
	}
}

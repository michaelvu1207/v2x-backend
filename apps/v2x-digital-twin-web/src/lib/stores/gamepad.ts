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
	const saved = localStorage.getItem('drive_calibration');
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
		localStorage.setItem('drive_calibration', JSON.stringify(cal));
	}
});

// ── Normalized Input (derived) ──

export interface NormalizedInput {
	steer: number; // -1 (left) to 1 (right)
	throttle: number; // 0 to 1
	brake: number; // 0 to 1
	reverse: boolean;
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

		// Pedals: raw is typically 1 (released) to -1 (pressed)
		// Normalize to 0 (released) to 1 (pressed)
		let throttle = $calibration.gasInverted ? (1 - rawGas) / 2 : (rawGas + 1) / 2;
		let brake = $calibration.brakeInverted ? (1 - rawBrake) / 2 : (rawBrake + 1) / 2;

		// Clamp and deadzone
		throttle = Math.max(0, Math.min(1, throttle));
		brake = Math.max(0, Math.min(1, brake));
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

	// Auto-detect pedal inversion from resting values
	const cal = get(calibration);
	const gasRest = axes[cal.gasAxis] ?? 0;
	const brakeRest = axes[cal.brakeAxis] ?? 0;

	// If pedals rest near +1.0, they need inversion (1→-1 range)
	// If pedals rest near -1.0, they don't (−1→+1 range)
	// If pedals rest near 0, they're probably 0→1 range (no inversion)
	const gasNeedsInvert = gasRest > 0.5;
	const brakeNeedsInvert = brakeRest > 0.5;

	if (gasNeedsInvert !== cal.gasInverted || brakeNeedsInvert !== cal.brakeInverted) {
		console.log(`[Gamepad] Auto-adjusting inversion: gas=${gasNeedsInvert}, brake=${brakeNeedsInvert} (resting: gas=${gasRest.toFixed(2)}, brake=${brakeRest.toFixed(2)})`);
		calibration.set({
			...cal,
			gasInverted: gasNeedsInvert,
			brakeInverted: brakeNeedsInvert,
		});
	}
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

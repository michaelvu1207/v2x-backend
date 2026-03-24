/**
 * Drive WebSocket Store — manages the connection to the drive server.
 *
 * Handles: connection lifecycle, session management, control message sending,
 * telemetry reception, and auto-reconnect.
 */

import { writable, get } from 'svelte/store';
import type { DriveSessionState, VehicleTelemetry, CameraView, DriveMessage } from '$lib/types';

// ── Stores ──

export const driveConnected = writable<boolean>(false);

// Callback for binary frames (MJPEG). Set by the drive page to push frames to CameraView.
let onFrameCallback: ((data: Blob) => void) | null = null;

export function setOnFrame(cb: ((data: Blob) => void) | null): void {
	onFrameCallback = cb;
}
export const sessionState = writable<DriveSessionState>('idle');
export const telemetry = writable<VehicleTelemetry>({
	speed: 0,
	gear: 0,
	pos: [0, 0, 0],
	rot: [0, 0, 0],
	steer: 0,
	throttle: 0,
	brake: 0,
});
export const lastError = writable<string | null>(null);
export const vehicleId = writable<number | null>(null);
export const objectsCount = writable<number>(0);

// ── WebSocket ──

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
const MAX_RECONNECT_DELAY = 8000;

export function connect(wsUrl: string): void {
	if (ws && ws.readyState === WebSocket.OPEN) return;

	sessionState.set('connecting');
	lastError.set(null);

	ws = new WebSocket(wsUrl);
	ws.binaryType = 'blob';

	ws.onopen = () => {
		driveConnected.set(true);
		reconnectAttempt = 0;
		console.log('[DriveWS] Connected');
	};

	ws.onmessage = (event) => {
		// Binary message = JPEG camera frame
		if (event.data instanceof Blob) {
			if (onFrameCallback) {
				onFrameCallback(event.data);
			}
			return;
		}

		// Text message = JSON (telemetry, session events, errors)
		try {
			const msg: DriveMessage = JSON.parse(event.data);
			handleServerMessage(msg);
		} catch (e) {
			console.warn('[DriveWS] Invalid message:', event.data);
		}
	};

	ws.onclose = () => {
		driveConnected.set(false);
		console.log('[DriveWS] Disconnected');

		// Auto-reconnect if we were in an active session
		const state = get(sessionState);
		if (state === 'driving' || state === 'ready') {
			scheduleReconnect(wsUrl);
		} else {
			sessionState.set('idle');
		}
	};

	ws.onerror = (e) => {
		console.error('[DriveWS] Error:', e);
		lastError.set('WebSocket connection error');
	};
}

export function disconnect(): void {
	if (reconnectTimer) {
		clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}
	if (ws) {
		ws.close();
		ws = null;
	}
	driveConnected.set(false);
	sessionState.set('idle');
}

function scheduleReconnect(wsUrl: string): void {
	const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY);
	reconnectAttempt++;
	console.log(`[DriveWS] Reconnecting in ${delay}ms (attempt ${reconnectAttempt})`);
	reconnectTimer = setTimeout(() => connect(wsUrl), delay);
}

// ── Message Handling ──

function handleServerMessage(msg: DriveMessage): void {
	switch (msg.type) {
		case 'session_ready':
			sessionState.set('driving');
			vehicleId.set(msg.vehicle_id as number);
			objectsCount.set(msg.objects_count as number);
			break;

		case 'telemetry':
			telemetry.set(msg as unknown as VehicleTelemetry);
			// If we receive telemetry, we're actively driving
			if (get(sessionState) === 'ready') {
				sessionState.set('driving');
			}
			break;

		case 'session_ended':
			sessionState.set('idle');
			vehicleId.set(null);
			break;

		case 'camera_switched':
			// Acknowledged — no state change needed
			break;

		case 'error':
			lastError.set(msg.message as string);
			if (get(sessionState) === 'reconstructing') {
				sessionState.set('error');
			}
			break;

		default:
			console.warn('[DriveWS] Unknown message type:', msg.type);
	}
}

// ── Actions ──

function send(msg: DriveMessage): void {
	if (ws && ws.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify(msg));
	}
}

export function startSession(start: string, end: string): void {
	sessionState.set('reconstructing');
	lastError.set(null);
	send({ type: 'start_session', start, end });
}

export function sendControl(steer: number, throttle: number, brake: number, reverse: boolean = false): void {
	send({ type: 'control', s: steer, t: throttle, b: brake, rev: reverse });
}

export function switchCamera(view: CameraView): void {
	send({ type: 'camera_switch', view });
}

export function respawnVehicle(): void {
	send({ type: 'respawn' });
}

export function endSession(): void {
	sessionState.set('ending');
	send({ type: 'end_session' });
}

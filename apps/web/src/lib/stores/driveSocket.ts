/**
 * Drive WebSocket Store — manages the connection to the drive server.
 *
 * Handles: connection lifecycle, session management, control message sending,
 * telemetry reception, and auto-reconnect.
 */

import { writable, get } from 'svelte/store';
import type { DriveSessionState, VehicleTelemetry, CameraView, DriveMessage, VehicleOption, SpawnableObject, PlacedObject, ScenarioInfo, V2xSignal, V2xAlert, V2xZone } from '$lib/types';
import { v2xZones } from './v2xZones';

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
export const vehicleList = writable<VehicleOption[]>([]);
export const spawnableObjects = writable<SpawnableObject[]>([]);
export const placedObjects = writable<PlacedObject[]>([]);
export const placedCount = writable<number>(0);
export const scenarioList = writable<ScenarioInfo[]>([]);
export const v2xSignals = writable<V2xSignal[]>([]);
export const v2xSignalCount = writable<number>(0);
export const v2xAlerts = writable<V2xAlert[]>([]);

// ── WebSocket ──

let ws: WebSocket | null = null;

export function connect(wsUrl: string): void {
	if (ws && ws.readyState === WebSocket.OPEN) return;

	sessionState.set('connecting');
	lastError.set(null);

	ws = new WebSocket(wsUrl);
	ws.binaryType = 'blob';

	ws.onopen = () => {
		driveConnected.set(true);
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

		// Don't auto-reconnect — it creates zombie state where the frontend
		// thinks it has a session but the server already cleaned up.
		// Just reset to idle and let the user start fresh.
		const state = get(sessionState);
		if (state !== 'idle') {
			console.log('[DriveWS] Session lost — resetting to idle');
			sessionState.set('idle');
			vehicleId.set(null);
		}
	};

	ws.onerror = (e) => {
		console.error('[DriveWS] Error:', e);
		lastError.set('WebSocket connection error');
	};
}

export function disconnect(): void {
	if (ws) {
		ws.close();
		ws = null;
	}
	driveConnected.set(false);
	sessionState.set('idle');
	vehicleId.set(null);
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
			// Handle V2X proximity alerts from telemetry
			if (msg.v2x_alerts) {
				v2xAlerts.update(existing => {
					const newAlerts = (msg.v2x_alerts as V2xAlert[]).map(a => ({
						...a,
						_uid: Date.now() + Math.random(),
					}));
					return [...existing, ...newAlerts];
				});
			}
			break;

		case 'session_ended':
			sessionState.set('idle');
			vehicleId.set(null);
			break;

		case 'vehicle_list':
			vehicleList.set((msg.vehicles as VehicleOption[]) ?? []);
			break;

		case 'object_list':
			spawnableObjects.set((msg.objects as SpawnableObject[]) ?? []);
			break;

		case 'object_spawned':
			placedObjects.update(list => [...list, {
				actor_id: msg.actor_id as number,
				blueprint: msg.blueprint as string,
				pos: msg.pos as [number, number, number],
			}]);
			placedCount.set(msg.placed_count as number);
			break;

		case 'object_removed':
			placedObjects.update(list => list.slice(0, -1));
			placedCount.set(msg.placed_count as number);
			break;

		case 'undo_empty':
			// Nothing to undo — no state change
			break;

		case 'scenario_list':
			scenarioList.set((msg.scenarios as ScenarioInfo[]) ?? []);
			break;

		case 'scenario_saved':
			// Refresh scenario list after save
			requestScenarios();
			break;

		case 'scenario_loaded':
			placedCount.set((msg.placed_count as number) ?? 0);
			if (Array.isArray(msg.zones)) {
				v2xZones.set(msg.zones as V2xZone[]);
			}
			break;

		case 'scenario_deleted':
			requestScenarios();
			break;

		case 'camera_switched':
			// Acknowledged — no state change needed
			break;

		case 'v2x_signal_placed':
			v2xSignals.update(list => [...list, msg.signal as V2xSignal]);
			v2xSignalCount.set(msg.signal_count as number);
			break;

		case 'v2x_signal_removed':
			v2xSignals.update(list => list.filter(s => s.id !== (msg.signal_id as number)));
			v2xSignalCount.set(msg.signal_count as number);
			break;

		case 'v2x_undo_empty':
			break;

		case 'v2x_signal_list':
			v2xSignals.set((msg.signals as V2xSignal[]) ?? []);
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

export function requestVehicles(): void {
	send({ type: 'list_vehicles' });
}

export function startSession(start: string, end: string, vehicle?: string): void {
	sessionState.set('reconstructing');
	lastError.set(null);
	send({ type: 'start_session', start, end, vehicle: vehicle ?? 'vehicle.tesla.model3' });
}

export function sendControl(steer: number, throttle: number, brake: number, reverse: boolean = false): void {
	// Don't send control if not actively driving
	if (get(sessionState) !== 'driving') return;
	send({ type: 'control', s: steer, t: throttle, b: brake, rev: reverse });
}

export function switchCamera(view: CameraView): void {
	send({ type: 'camera_switch', view });
}

export function respawnVehicle(): void {
	send({ type: 'respawn' });
}

export function requestObjects(): void {
	send({ type: 'list_objects' });
}

export function spawnObject(blueprint: string, offset: number = 8.0): void {
	send({ type: 'spawn_object', blueprint, offset });
}

export function undoPlace(): void {
	send({ type: 'undo_place' });
}

export function requestScenarios(): void {
	send({ type: 'list_scenarios' });
}

export function saveScenario(name: string, zones: V2xZone[] = []): void {
	send({ type: 'save_scenario', name, zones });
}

export function loadScenario(file: string): void {
	send({ type: 'load_scenario', file });
}

export function deleteScenario(file: string): void {
	send({ type: 'delete_scenario', file });
}

export function endSession(): void {
	sessionState.set('ending');
	send({ type: 'end_session' });
}

// ── V2X Signal Actions ──

export function placeV2xSignal(message: string, signalType: string = 'warning', radius: number = 30.0): void {
	send({ type: 'place_v2x_signal', message, signal_type: signalType, radius });
}

export function removeV2xSignal(signalId: number): void {
	send({ type: 'remove_v2x_signal', signal_id: signalId });
}

export function undoV2xSignal(): void {
	send({ type: 'undo_v2x_signal' });
}

export function requestV2xSignals(): void {
	send({ type: 'list_v2x_signals' });
}

export function dismissV2xAlert(alertId: number): void {
	v2xAlerts.update(list => list.filter(a => a.id !== alertId));
}

// ── Weather Actions ──

export function setWeather(params: Record<string, number>): void {
	send({ type: 'set_weather', params });
}

export function setCameraSettings(params: Record<string, string | number>): void {
	send({ type: 'set_camera_settings', params });
}

// ── Traffic Actions ──

export function spawnTraffic(preset: string): void {
	send({ type: 'spawn_traffic', preset });
}

export function despawnTraffic(): void {
	send({ type: 'despawn_traffic' });
}

// ── V2X Zone Actions ──

export function syncV2xZones(zones: { polygon: [number, number][]; signal_type: string; color: string }[]): void {
	send({ type: 'sync_v2x_zones', zones });
}


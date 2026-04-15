import { writable } from 'svelte/store';
import { POLL_INTERVAL } from '$lib/constants';
import { objects, bridgeStatus } from './objects';
import { fetchState } from '$lib/api';

/** Whether the polling loop is actively fetching data. */
export const wsConnected = writable<boolean>(false);

let pollTimer: ReturnType<typeof setInterval> | null = null;
let polling = false;

async function poll(): Promise<void> {
	if (polling) return;
	polling = true;

	try {
		const state = await fetchState();

		// Update all objects from state
		objects.setAll(state.objects);

		// Update bridge status
		bridgeStatus.set({
			status: state.bridge_status.status === 'connected' ? 'connected' : 'disconnected',
			carla_fps: state.bridge_status.carla_fps ?? 0,
			objects_tracked: state.bridge_status.objects_tracked ?? 0,
			cameras_active: state.bridge_status.cameras_active ?? 0,
			last_heartbeat: Date.now()
		});

		wsConnected.set(true);
	} catch (err) {
		console.warn('[Poll] Failed to fetch state:', err);
		wsConnected.set(false);
		bridgeStatus.update((s) => ({ ...s, status: 'disconnected' }));
	} finally {
		polling = false;
	}
}

/**
 * Start polling state from the read API.
 */
export function connectWebSocket(): void {
	if (pollTimer) return;

	console.log(`[Poll] Starting state polling every ${POLL_INTERVAL}ms`);
	poll(); // initial fetch
	pollTimer = setInterval(poll, POLL_INTERVAL);
}

/**
 * Stop polling.
 */
export function disconnectWebSocket(): void {
	if (pollTimer) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
	wsConnected.set(false);
}

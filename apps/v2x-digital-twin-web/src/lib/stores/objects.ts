import { writable, derived } from 'svelte/store';
import type { TrackedObject, BridgeStatus } from '$lib/types';

/**
 * Store holding all tracked objects keyed by object_id.
 */
function createObjectsStore() {
	const { subscribe, set, update } = writable<Map<string, TrackedObject>>(new Map());

	return {
		subscribe,
		set,
		update,

		/** Merge a fresh list of objects, only updating entries that changed. */
		setAll(objectList: TrackedObject[]) {
			update((prev) => {
				const incoming = new Set<string>();
				let changed = false;

				for (const obj of objectList) {
					incoming.add(obj.object_id);
					const existing = prev.get(obj.object_id);
					if (
						!existing ||
						existing.snapshot_url !== obj.snapshot_url ||
						existing.snapshot_timestamp !== obj.snapshot_timestamp ||
						existing.lat !== obj.lat ||
						existing.lon !== obj.lon ||
						existing.confidence !== obj.confidence
					) {
						prev.set(obj.object_id, obj);
						changed = true;
					}
				}

				// Remove objects no longer present
				for (const id of prev.keys()) {
					if (!incoming.has(id)) {
						prev.delete(id);
						changed = true;
					}
				}

				// Return new Map only if something changed (triggers reactivity)
				return changed ? new Map(prev) : prev;
			});
		},

		/** Add or update a single object. */
		upsert(obj: TrackedObject) {
			update((map) => {
				const updated = new Map(map);
				updated.set(obj.object_id, {
					...obj,
					last_updated: Date.now()
				});
				return updated;
			});
		},

		/** Remove an object by ID. */
		remove(id: string) {
			update((map) => {
				const updated = new Map(map);
				updated.delete(id);
				return updated;
			});
		},

		/** Update only the snapshot fields on an existing object. */
		updateSnapshot(objectId: string, snapshotUrl: string, snapshotTimestamp: string) {
			update((map) => {
				const existing = map.get(objectId);
				if (!existing) return map;

				const updated = new Map(map);
				updated.set(objectId, {
					...existing,
					snapshot_url: snapshotUrl,
					snapshot_timestamp: snapshotTimestamp,
					last_updated: Date.now()
				});
				return updated;
			});
		}
	};
}

export const objects = createObjectsStore();

/**
 * Derived store: array of all tracked objects sorted by object_id.
 */
export const objectList = derived(objects, ($objects) =>
	Array.from($objects.values()).sort((a, b) => a.object_id.localeCompare(b.object_id))
);

/**
 * Bridge / system status store.
 */
export const bridgeStatus = writable<BridgeStatus>({
	status: 'disconnected',
	carla_fps: 0,
	objects_tracked: 0,
	cameras_active: 0,
	last_heartbeat: 0
});

/**
 * Currently selected object ID (for detail panel).
 */
export const selectedObjectId = writable<string | null>(null);

/**
 * Derived: the full TrackedObject for the currently selected ID, or null.
 */
export const selectedObject = derived(
	[objects, selectedObjectId],
	([$objects, $selectedId]) => {
		if ($selectedId === null) return null;
		return $objects.get($selectedId) ?? null;
	}
);

/**
 * Helper: update an object from an incoming WebSocket payload.
 */
export function updateObject(obj: TrackedObject): void {
	objects.upsert(obj);
}

/**
 * Helper: remove an object by ID.
 */
export function removeObject(id: string): void {
	objects.remove(id);
}

/**
 * Helper: update snapshot on an object.
 */
export function updateSnapshot(
	objectId: string,
	snapshotUrl: string,
	snapshotTimestamp: string
): void {
	objects.updateSnapshot(objectId, snapshotUrl, snapshotTimestamp);
}

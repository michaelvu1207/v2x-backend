/**
 * V2X Zone Store — manages drawn V2X zones and proximity detection.
 *
 * Zones are drawn on the pre-drive map editor and persisted to localStorage.
 * During driving, the store checks if the car's position falls inside any
 * zone and fires alerts via the existing V2xToast system.
 *
 * Coordinate conversion: CARLA UE4 world coords → GPS [lon, lat]
 * using the geo-reference origin from the /map-data API.
 */

import { writable, get } from 'svelte/store';
import type { V2xZone, V2xAlert } from '$lib/types';

const STORAGE_KEY = 'v2x-zones';

// ── Zone CRUD Store ──

function loadFromStorage(): V2xZone[] {
	if (typeof localStorage === 'undefined') return [];
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		return raw ? JSON.parse(raw) : [];
	} catch {
		return [];
	}
}

function saveToStorage(zones: V2xZone[]): void {
	if (typeof localStorage === 'undefined') return;
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(zones));
	} catch {
		// Storage full or unavailable
	}
}

export const v2xZones = writable<V2xZone[]>(loadFromStorage());

// Auto-persist on change
v2xZones.subscribe(saveToStorage);

export function addZone(zone: V2xZone): void {
	v2xZones.update((zones) => [...zones, zone]);
}

export function updateZone(id: string, updates: Partial<V2xZone>): void {
	v2xZones.update((zones) =>
		zones.map((z) => (z.id === id ? { ...z, ...updates } : z))
	);
}

export function removeZone(id: string): void {
	v2xZones.update((zones) => zones.filter((z) => z.id !== id));
}

export function clearZones(): void {
	v2xZones.set([]);
}

// ── Coordinate Conversion ──

/**
 * Convert CARLA UE4 world coordinates to GPS [lon, lat].
 *
 * CARLA uses a left-handed coordinate system where Y is inverted
 * relative to real-world north. The formula mirrors geo_utils.py.
 */
export function carlaToGps(
	x: number,
	y: number,
	originLat: number,
	originLon: number
): [number, number] {
	const METERS_PER_DEGREE = 111320;
	const lat = originLat - y / METERS_PER_DEGREE;
	const lon =
		originLon + x / (METERS_PER_DEGREE * Math.cos((originLat * Math.PI) / 180));
	return [lon, lat];
}

// ── Point-in-Polygon (ray casting) ──

export function pointInPolygon(
	point: [number, number],
	polygon: [number, number][]
): boolean {
	let inside = false;
	for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
		const xi = polygon[i][0],
			yi = polygon[i][1];
		const xj = polygon[j][0],
			yj = polygon[j][1];
		if (
			yi > point[1] !== yj > point[1] &&
			point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi
		) {
			inside = !inside;
		}
	}
	return inside;
}

// ── Proximity Detection ──

// Track which zones the car is currently inside (for re-entry detection)
const triggeredZones = new Set<string>();

/**
 * Check if a CARLA position is inside any V2X zone.
 * Returns alerts for newly entered zones. Resets when the car exits.
 */
export function checkZoneProximity(
	carlaX: number,
	carlaY: number,
	originLat: number,
	originLon: number
): V2xAlert[] {
	const gpsPos = carlaToGps(carlaX, carlaY, originLat, originLon);
	const zones = get(v2xZones);
	const alerts: V2xAlert[] = [];

	const currentlyInside = new Set<string>();

	for (const zone of zones) {
		if (zone.polygon.length < 3) continue;

		if (pointInPolygon(gpsPos, zone.polygon)) {
			currentlyInside.add(zone.id);

			// Fire alert only on entry (not while still inside)
			if (!triggeredZones.has(zone.id)) {
				alerts.push({
					id: Date.now() + Math.random(),
					message: zone.message || zone.name,
					signal_type: zone.signal_type,
					distance: 0,
				});
			}
		}
	}

	// Update triggered state: zones we left get cleared for re-entry
	for (const id of triggeredZones) {
		if (!currentlyInside.has(id)) {
			triggeredZones.delete(id);
		}
	}
	for (const id of currentlyInside) {
		triggeredZones.add(id);
	}

	return alerts;
}

/** Reset triggered state (call when ending a session). */
export function resetZoneProximity(): void {
	triggeredZones.clear();
}

import { buildAssetUrl, loadRuntimeConfig } from './runtime-config';
import type {
	DetectionPage,
	DetectionQueryMode,
	VideoSession
} from './types';

interface StateJson {
	objects: import('./types').TrackedObject[];
	bridge_status: import('./types').BridgeStatus;
	updated_at: string;
}

/**
 * Fetch the current state from S3 (state.json).
 * This is the primary data source — polled every few seconds.
 */
export async function fetchState(): Promise<StateJson> {
	const config = await loadRuntimeConfig();
	const url = `${buildAssetUrl(config.stateBaseUrl, config.statePath)}?_t=${Date.now()}`;
	const response = await fetch(url);

	if (!response.ok) {
		throw new Error(`Failed to fetch state: ${response.status}`);
	}

	return response.json() as Promise<StateJson>;
}

/**
 * Fetch road polyline data for the map overlay from S3.
 * Returns an array of polylines, each polyline is an array of [lon, lat] pairs.
 */
export async function fetchMapData(): Promise<number[][][]> {
	const config = await loadRuntimeConfig();
	const url = buildAssetUrl(config.stateBaseUrl, config.mapDataPath);
	const response = await fetch(url);

	if (!response.ok) {
		throw new Error(`Failed to fetch map data: ${response.status}`);
	}

	const data = (await response.json()) as { road_network: number[][][] };
	return data.road_network;
}

export async function fetchVideoSession(cameraId: string): Promise<VideoSession> {
	const config = await loadRuntimeConfig();
	const response = await fetch(
		`${config.apiBaseUrl.replace(/\/+$/, '')}/video/session/${encodeURIComponent(cameraId)}`,
		{ cache: 'no-store' }
	);

	if (!response.ok) {
		let detail = `${response.status}`;
		try {
			const body = (await response.json()) as { detail?: string; error?: string };
			detail = body.detail || body.error || detail;
		} catch {
			// Keep the HTTP status fallback.
		}
		throw new Error(`Failed to fetch video session: ${detail}`);
	}

	return (await response.json()) as VideoSession;
}

function buildDetectionsUrl(
	mode: DetectionQueryMode,
	query: string,
	limit: number,
	next: string | null,
	config: Awaited<ReturnType<typeof loadRuntimeConfig>>
): string {
	const base = config.detectionsApiBaseUrl.replace(/\/+$/, '');
	let path = config.detectionRoutes.recent;

	if (mode === 'object') {
		path = config.detectionRoutes.byObject.replace('{object_id}', encodeURIComponent(query));
	} else if (mode === 'geohash') {
		path = config.detectionRoutes.byGeohash.replace('{geohash}', encodeURIComponent(query));
	}

	const url = new URL(`${base}${path}`);
	url.searchParams.set('limit', String(limit));
	if (next) {
		url.searchParams.set('next', next);
	}
	return url.toString();
}

export async function fetchDetectionsPage(options: {
	mode: DetectionQueryMode;
	query?: string;
	limit?: number;
	next?: string | null;
}): Promise<DetectionPage> {
	const config = await loadRuntimeConfig();
	const response = await fetch(
		buildDetectionsUrl(
			options.mode,
			options.query?.trim() || '',
			options.limit || 50,
			options.next || null,
			config
		),
		{
			headers: { accept: 'application/json' },
			cache: 'no-store'
		}
	);

	if (!response.ok) {
		throw new Error(`Failed to fetch detections: ${response.status}`);
	}

	return (await response.json()) as DetectionPage;
}

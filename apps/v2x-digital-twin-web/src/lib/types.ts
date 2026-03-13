export interface TrackedObject {
	object_id: string;
	object_type: 'traffic_cone' | 'vehicle' | 'walker' | string;
	lat: number;
	lon: number;
	confidence: number;
	street_name: string;
	timestamp_utc: string;
	snapshot_url: string | null;
	snapshot_timestamp: string | null;
	last_updated: number; // unix ms
}

export interface BridgeStatus {
	status: 'connected' | 'disconnected' | 'error';
	carla_fps: number;
	objects_tracked: number;
	cameras_active: number;
	last_heartbeat: number;
}

export interface SnapshotHistoryEntry {
	url: string;
	timestamp: string;
	object_id: string;
}

export interface VideoSession {
	cameraId: string;
	streamName: string;
	playbackMode: 'LIVE' | string;
	hlsUrl: string;
	expiresIn: number;
	region: string;
}

export type DetectionQueryMode = 'recent' | 'object' | 'geohash';

export interface DetectionItem {
	object_id?: string;
	object_type?: string | null;
	geohash?: string | null;
	confidence_score?: number | string | null;
	device_id?: string | null;
	timestamp_utc?: string | null;
}

export interface DetectionPage {
	items?: DetectionItem[];
	next?: string | null;
}

export type FreshnessLevel = 'fresh' | 'stale' | 'old';

interface DetectionRoutes {
	recent: string;
	byObject: string;
	byGeohash: string;
}

export interface RuntimeConfig {
	apiBaseUrl: string;
	detectionsApiBaseUrl: string;
	detectionRoutes: DetectionRoutes;
	stateBaseUrl: string;
	statePath: string;
	mapDataPath: string;
	videoCameraIds: string[];
}

const DEFAULT_CONFIG: RuntimeConfig = {
	apiBaseUrl: 'https://w0j9m7dgpg.execute-api.us-west-1.amazonaws.com',
	detectionsApiBaseUrl: 'https://w0j9m7dgpg.execute-api.us-west-1.amazonaws.com',
	detectionRoutes: {
		recent: '/detections/recent',
		byObject: '/detections/object/{object_id}',
		byGeohash: '/detections/geohash/{geohash}'
	},
	stateBaseUrl: 'https://v2x-backend-state-147229569658-us-west-1.s3.us-west-1.amazonaws.com',
	statePath: '/api/state.json',
	mapDataPath: '/api/map-data.json',
	videoCameraIds: ['ch1', 'ch2', 'ch3', 'ch4']
};

let configPromise: Promise<RuntimeConfig> | null = null;

function withDefaultPath(path: string | undefined, fallback: string): string {
	if (!path) return fallback;
	return path.startsWith('/') ? path : `/${path}`;
}

function normalizeConfig(config: Partial<RuntimeConfig>): RuntimeConfig {
	return {
		apiBaseUrl: config.apiBaseUrl || DEFAULT_CONFIG.apiBaseUrl,
		detectionsApiBaseUrl: (
			config.detectionsApiBaseUrl ||
			config.apiBaseUrl ||
			DEFAULT_CONFIG.detectionsApiBaseUrl
		).replace(/\/+$/, ''),
		detectionRoutes: {
			recent: withDefaultPath(
				config.detectionRoutes?.recent,
				DEFAULT_CONFIG.detectionRoutes.recent
			),
			byObject: withDefaultPath(
				config.detectionRoutes?.byObject,
				DEFAULT_CONFIG.detectionRoutes.byObject
			),
			byGeohash: withDefaultPath(
				config.detectionRoutes?.byGeohash,
				DEFAULT_CONFIG.detectionRoutes.byGeohash
			)
		},
		stateBaseUrl: (config.stateBaseUrl || DEFAULT_CONFIG.stateBaseUrl).replace(/\/+$/, ''),
		statePath: withDefaultPath(config.statePath, DEFAULT_CONFIG.statePath),
		mapDataPath: withDefaultPath(config.mapDataPath, DEFAULT_CONFIG.mapDataPath),
		videoCameraIds: config.videoCameraIds || DEFAULT_CONFIG.videoCameraIds
	};
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
	if (!configPromise) {
		configPromise = fetch('/config.json', { cache: 'no-store' })
			.then(async (response) => {
				if (!response.ok) {
					return DEFAULT_CONFIG;
				}
				return normalizeConfig((await response.json()) as Partial<RuntimeConfig>);
			})
			.catch(() => DEFAULT_CONFIG);
	}

	return configPromise;
}

export function buildAssetUrl(baseUrl: string, path: string): string {
	return `${baseUrl.replace(/\/+$/, '')}${withDefaultPath(path, '/')}`;
}

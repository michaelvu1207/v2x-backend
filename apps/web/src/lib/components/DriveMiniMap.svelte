<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import { MAP_CENTER, DEFAULT_ZOOM, MAP_STYLE_URL } from '$lib/constants';
	import { telemetry } from '$lib/stores/driveSocket';
	import { v2xZones } from '$lib/stores/v2xZones';
	import { carlaToGps } from '$lib/stores/v2xZones';
	import type { V2xZone } from '$lib/types';

	interface Props {
		roadLines: number[][][];
		originLat: number;
		originLon: number;
	}

	let { roadLines, originLat, originLon }: Props = $props();

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = null;
	let carMarker: maplibregl.Marker | null = null;
	let mapReady = $state(false);
	let expanded = $state(false);

	onMount(() => {
		map = new maplibregl.Map({
			container: mapContainer,
			style: MAP_STYLE_URL,
			center: [originLon || MAP_CENTER.lon, originLat || MAP_CENTER.lat],
			zoom: DEFAULT_ZOOM + 1,
			attributionControl: false,
			dragPan: false,
			dragRotate: false,
			keyboard: false,
			doubleClickZoom: false,
			touchZoomRotate: false,
			scrollZoom: true,
		});

		map.on('load', () => {
			if (!map) return;
			mapReady = true;

			// Road network
			if (roadLines.length > 0) {
				map.addSource('roads', {
					type: 'geojson',
					data: buildRoadGeoJSON(roadLines),
				});
				map.addLayer({
					id: 'roads-layer',
					type: 'line',
					source: 'roads',
					paint: {
						'line-color': '#6b7280',
						'line-width': 1.5,
						'line-opacity': 0.5,
					},
				});
			}

			// V2X zones
			map.addSource('v2x-zones', {
				type: 'geojson',
				data: buildZonesGeoJSON($v2xZones),
			});
			map.addLayer({
				id: 'v2x-zones-fill',
				type: 'fill',
				source: 'v2x-zones',
				paint: {
					'fill-color': ['get', 'color'],
					'fill-opacity': 0.3,
				},
			});
			map.addLayer({
				id: 'v2x-zones-outline',
				type: 'line',
				source: 'v2x-zones',
				paint: {
					'line-color': ['get', 'color'],
					'line-width': 1.5,
					'line-opacity': 0.7,
				},
			});

			// Car marker — directional arrow that rotates with heading
			const el = document.createElement('div');
			el.className = 'car-marker';
			el.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" style="filter: drop-shadow(0 0 4px rgba(34, 211, 238, 0.6));">
				<polygon points="12,2 4,20 12,16 20,20" fill="#22d3ee" stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/>
			</svg>`;
			el.style.width = '24px';
			el.style.height = '24px';

			carMarker = new maplibregl.Marker({ element: el, rotationAlignment: 'map' })
				.setLngLat([originLon || MAP_CENTER.lon, originLat || MAP_CENTER.lat])
				.addTo(map);
		});
	});

	// Update car position from telemetry
	let frameCount = 0;
	$effect(() => {
		const t = $telemetry;
		if (!map || !mapReady || !carMarker) return;

		// Throttle to ~5fps (every 4th telemetry update at 20fps)
		frameCount++;
		if (frameCount % 4 !== 0) return;

		const [lon, lat] = carlaToGps(t.pos[0], t.pos[1], originLat, originLon);
		carMarker.setLngLat([lon, lat]);
		// CARLA yaw: 0=forward(+X), 90=right(+Y). MapLibre bearing: 0=north, 90=east.
		// Negate because CARLA Y-axis is inverted relative to GPS north.
		carMarker.setRotation(-t.rot[1]);
		map.setCenter([lon, lat]);
	});

	// Update zone overlays when zones change
	$effect(() => {
		const zones = $v2xZones;
		if (!map || !mapReady) return;
		const source = map.getSource('v2x-zones') as maplibregl.GeoJSONSource | undefined;
		if (source) {
			source.setData(buildZonesGeoJSON(zones));
		}
	});

	function buildRoadGeoJSON(lines: number[][][]): GeoJSON.FeatureCollection {
		return {
			type: 'FeatureCollection',
			features: lines.map((coords) => ({
				type: 'Feature' as const,
				geometry: { type: 'LineString' as const, coordinates: coords },
				properties: {},
			})),
		};
	}

	function buildZonesGeoJSON(zones: V2xZone[]): GeoJSON.FeatureCollection {
		return {
			type: 'FeatureCollection',
			features: zones
				.filter((z) => z.polygon.length >= 3)
				.map((z) => ({
					type: 'Feature' as const,
					geometry: {
						type: 'Polygon' as const,
						coordinates: [z.polygon],
					},
					properties: {
						color: z.color,
						name: z.name,
					},
				})),
		};
	}

	onDestroy(() => {
		if (carMarker) carMarker.remove();
		if (map) map.remove();
		map = null;
		carMarker = null;
	});
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="absolute left-3 top-3 z-30 overflow-hidden rounded-lg border border-gray-700/60 bg-gray-900/80 shadow-xl backdrop-blur-sm transition-all duration-200"
	style="width: {expanded ? 400 : 220}px; height: {expanded ? 300 : 160}px;"
	onclick={() => { expanded = !expanded; setTimeout(() => map?.resize(), 210); }}
>
	<div bind:this={mapContainer} class="h-full w-full"></div>

	<!-- Zoom controls -->
	<div class="absolute top-1 right-1 z-10 flex flex-col gap-0.5 pointer-events-auto"
		onclick={(e) => e.stopPropagation()}>
		<button
			class="w-6 h-6 rounded bg-gray-800/90 border border-gray-700/60 text-gray-300 hover:text-white hover:bg-gray-700 text-xs font-bold flex items-center justify-center transition-colors"
			onclick={(e) => { e.stopPropagation(); if (map) map.zoomIn(); }}
		>+</button>
		<button
			class="w-6 h-6 rounded bg-gray-800/90 border border-gray-700/60 text-gray-300 hover:text-white hover:bg-gray-700 text-xs font-bold flex items-center justify-center transition-colors"
			onclick={(e) => { e.stopPropagation(); if (map) map.zoomOut(); }}
		>-</button>
	</div>

	<!-- Zone count badge -->
	{#if $v2xZones.length > 0}
		<div class="absolute bottom-1 right-1 rounded bg-gray-900/80 px-1.5 py-0.5 text-[9px] font-medium text-gray-400">
			{$v2xZones.length} zone{$v2xZones.length !== 1 ? 's' : ''}
		</div>
	{/if}
</div>

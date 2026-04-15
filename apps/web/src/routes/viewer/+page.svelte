<script lang="ts">
	import { onMount } from 'svelte';
	import Header from '$lib/components/Header.svelte';
	import { fetchDetectionsPage } from '$lib/api';
	import { loadRuntimeConfig } from '$lib/runtime-config';
	import type { DetectionItem } from '$lib/types';

	let items = $state<DetectionItem[]>([]);
	let isLoading = $state(false);
	let error = $state<string | null>(null);
	let showDocumentation = $state(false);
	let apiBaseUrl = $state('https://w0j9m7dgpg.execute-api.us-west-1.amazonaws.com');

	function displayValue(value: DetectionItem[keyof DetectionItem]): string {
		return value == null ? '' : String(value);
	}

	async function loadItems() {
		error = null;
		isLoading = true;

		try {
			const response = await fetchDetectionsPage({
				mode: 'recent',
				limit: 100
			});
			items = response.items || [];
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to fetch detections.';
		} finally {
			isLoading = false;
		}
	}

	onMount(async () => {
		const config = await loadRuntimeConfig();
		apiBaseUrl = config.detectionsApiBaseUrl || config.apiBaseUrl;
		await loadItems();
	});
</script>

<svelte:head>
	<title>v2x-backend Objects DB</title>
</svelte:head>

<div class="flex h-screen flex-col overflow-hidden bg-gray-950">
	<Header />

	<main class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-4">
			<div class="flex items-center justify-between gap-4">
				<h1 class="mt-2 text-2xl font-semibold text-white">Objects Table</h1>
				<button
					class="border border-gray-700 bg-gray-900 px-3 py-2 text-sm font-medium text-gray-200 transition hover:border-gray-500 hover:text-white"
					onclick={() => {
						showDocumentation = !showDocumentation;
					}}
				>
					{showDocumentation ? 'Show table' : 'Show documentation'}
				</button>
			</div>

			{#if error}
				<p class="text-sm text-red-300">{error}</p>
			{/if}

			{#if showDocumentation}
				<div class="space-y-6 text-sm text-gray-300">
					<div class="space-y-2">
						<h2 class="text-base font-semibold text-white">Write Endpoint</h2>
						<p>
							POST objects to
							<span class="font-mono text-cyan-200">{apiBaseUrl}/detections</span>
						</p>
						<p class="text-gray-400">
							Accepted body shapes: a single object, an array of objects, or a wrapper object with
							an <span class="font-mono">items</span> array. Batch limit is 500 items.
						</p>
					</div>

					<div class="space-y-2">
						<h2 class="text-base font-semibold text-white">Minimum Payload</h2>
						<pre class="overflow-auto border border-gray-800 px-4 py-4 font-mono text-xs text-gray-300">{`curl -X POST \\
  -H 'content-type: application/json' \\
  -d '{
    "object_id": "traffic_cone_001",
    "timestamp_utc": "2026-02-05T00:00:00Z"
  }' \\
  '${apiBaseUrl}/detections'`}</pre>
					</div>

					<div class="space-y-2">
						<h2 class="text-base font-semibold text-white">Full Object Example</h2>
						<pre class="overflow-auto border border-gray-800 px-4 py-4 font-mono text-xs text-gray-300">{`curl -X POST \\
  -H 'content-type: application/json' \\
  -d '{
    "event_id": "01J0TESTULID00000000000000",
    "device_id": "edge-device-001",
    "object_id": "traffic_cone_001",
    "object_type": "traffic_cone",
    "gps_location": { "latitude": 37.915425, "longitude": -122.33492 },
    "geohash": "f43h7",
    "timestamp_utc": "2026-02-05T20:59:19Z",
    "street_name_normalized": "owl_wy",
    "global_context": { "city": "San Francisco", "state": "CA", "country": "USA" },
    "confidence_score": 0.78,
    "camera_data": { "image_reference_url": "", "svo2_reference_url": "", "bifocal_metadata": {} },
    "notes": "Traffic cone example"
  }' \\
  '${apiBaseUrl}/detections'`}</pre>
					</div>

					<div class="space-y-2">
						<h2 class="text-base font-semibold text-white">Batch Example</h2>
						<pre class="overflow-auto border border-gray-800 px-4 py-4 font-mono text-xs text-gray-300">{`curl -X POST \\
  -H 'content-type: application/json' \\
  -d '{
    "items": [
      { "object_id": "traffic_cone_001", "timestamp_utc": "2026-02-05T20:59:19Z" },
      { "object_id": "traffic_cone_002", "timestamp_utc": "2026-02-05T20:59:20Z" }
    ]
  }' \\
  '${apiBaseUrl}/detections'`}</pre>
					</div>
				</div>
			{:else}
				<div class="overflow-auto border border-gray-800">
					<table class="min-w-full border-collapse text-left text-sm">
						<thead class="bg-gray-950">
							<tr class="border-b border-gray-800 text-[11px] tracking-[0.2em] text-gray-500 uppercase">
								<th class="px-4 py-3 font-medium">timestamp_utc</th>
								<th class="px-4 py-3 font-medium">object_id</th>
								<th class="px-4 py-3 font-medium">type</th>
								<th class="px-4 py-3 font-medium">geohash</th>
								<th class="px-4 py-3 font-medium">confidence</th>
								<th class="px-4 py-3 font-medium">device</th>
							</tr>
						</thead>
						<tbody class="font-mono text-xs text-gray-200">
							{#if isLoading}
								<tr>
									<td colspan="6" class="px-4 py-10 text-center text-sm text-gray-500">
										Loading...
									</td>
								</tr>
							{:else if items.length === 0}
								<tr>
									<td colspan="6" class="px-4 py-10 text-center text-sm text-gray-500">
										No detections returned for this query yet.
									</td>
								</tr>
							{:else}
								{#each items as item}
									<tr class="border-b border-gray-900/80 transition hover:bg-white/[0.03]">
										<td class="px-4 py-3 align-top">{displayValue(item.timestamp_utc)}</td>
										<td class="px-4 py-3 align-top">{displayValue(item.object_id)}</td>
										<td class="px-4 py-3 align-top">{displayValue(item.object_type)}</td>
										<td class="px-4 py-3 align-top">{displayValue(item.geohash)}</td>
										<td class="px-4 py-3 align-top">{displayValue(item.confidence_score)}</td>
										<td class="px-4 py-3 align-top">{displayValue(item.device_id)}</td>
									</tr>
								{/each}
							{/if}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</main>
</div>

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import Hls from 'hls.js';
	import { fetchVideoSession } from '$lib/api';

	interface Props {
		cameraId: string;
	}

	let { cameraId }: Props = $props();

	let videoEl = $state<HTMLVideoElement | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let connected = $state(false);
	let sessionExpiresIn = $state<number | null>(null);
	let hls: Hls | null = null;
	let refreshTimer: ReturnType<typeof setTimeout> | null = null;

	function clearRefreshTimer() {
		if (refreshTimer) {
			clearTimeout(refreshTimer);
			refreshTimer = null;
		}
	}

	function scheduleRefresh(expiresIn: number | null) {
		clearRefreshTimer();
		if (!expiresIn || expiresIn <= 20) return;
		refreshTimer = setTimeout(() => {
			void connect();
		}, (expiresIn - 15) * 1000);
	}

	function destroyPlayer() {
		clearRefreshTimer();
		if (hls) {
			hls.destroy();
			hls = null;
		}
		if (videoEl) {
			videoEl.pause();
			videoEl.removeAttribute('src');
			videoEl.load();
		}
		connected = false;
	}

	async function connect() {
		loading = true;
		error = null;
		destroyPlayer();

		try {
			const session = await fetchVideoSession(cameraId);
			sessionExpiresIn = session.expiresIn;
			scheduleRefresh(session.expiresIn);

			if (!videoEl) {
				throw new Error('Video element unavailable');
			}

			if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
				videoEl.src = session.hlsUrl;
			} else if (Hls.isSupported()) {
				hls = new Hls({
					enableWorker: true,
					lowLatencyMode: false,
				});
				hls.loadSource(session.hlsUrl);
				hls.attachMedia(videoEl);
			} else {
				throw new Error('HLS playback is not supported in this browser');
			}

			await videoEl.play().catch(() => {});
			connected = true;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Unknown playback error';
			destroyPlayer();
		} finally {
			loading = false;
		}
	}

	onDestroy(() => {
		destroyPlayer();
	});

	onMount(() => {
		void connect();
	});
</script>

<div class="relative overflow-hidden border border-gray-900 bg-black" style="aspect-ratio: 4 / 3;">
	<div class="absolute top-2 left-2 z-10 bg-black/70 px-2 py-1 text-[10px] font-medium tracking-[0.18em] text-gray-200 uppercase">
		{cameraId}
	</div>

	<div class="absolute top-2 right-2 z-10 flex items-center gap-2">
		{#if connected}
			<span class="bg-red-600 px-2 py-1 text-[10px] font-semibold tracking-[0.16em] text-white uppercase">
				Live
			</span>
		{/if}
		{#if sessionExpiresIn}
			<span class="bg-black/70 px-2 py-1 text-[10px] text-gray-400">
				{sessionExpiresIn}s
			</span>
		{/if}
	</div>

	<div class="absolute inset-0">
		<video
			bind:this={videoEl}
			class="h-full w-full object-cover"
			playsinline
			muted
		></video>

		{#if !connected && !loading}
			<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/55">
				<button
					class="border border-gray-600 bg-black/80 px-4 py-2 text-[11px] font-medium tracking-[0.16em] text-white uppercase hover:border-gray-400"
					onclick={connect}
				>
					Reconnect
				</button>
			</div>
		{/if}

		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center bg-black/45">
				<div class="h-8 w-8 animate-spin rounded-full border-2 border-gray-700 border-t-cyan-300"></div>
			</div>
		{/if}
	</div>

	{#if error}
		<div class="absolute right-0 bottom-0 left-0 z-10 bg-black/85 px-3 py-2 text-[11px] text-rose-300">
			{error}
		</div>
	{/if}
</div>

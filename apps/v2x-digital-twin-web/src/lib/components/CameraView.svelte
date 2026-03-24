<script lang="ts">
	import { CAMERA_VIEWS } from '$lib/constants';
	import type { CameraView } from '$lib/types';

	interface Props {
		activeView: CameraView;
		onSwitchView: (view: CameraView) => void;
	}
	let { activeView, onSwitchView }: Props = $props();

	let imgSrc = $state<string | null>(null);
	let frameCount = $state(0);

	// Keyboard shortcuts for camera views
	function handleKeydown(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
		const view = CAMERA_VIEWS.find((v) => v.key === e.key);
		if (view) {
			onSwitchView(view.id as CameraView);
		}
	}

	$effect(() => {
		window.addEventListener('keydown', handleKeydown);
		return () => window.removeEventListener('keydown', handleKeydown);
	});

	/**
	 * Feed a JPEG frame (as a Blob or ArrayBuffer) into the view.
	 * Called by the parent when a binary WebSocket message arrives.
	 */
	export function pushFrame(data: Blob | ArrayBuffer) {
		// Revoke previous object URL to prevent memory leak
		if (imgSrc) {
			URL.revokeObjectURL(imgSrc);
		}

		const blob = data instanceof Blob ? data : new Blob([data], { type: 'image/jpeg' });
		imgSrc = URL.createObjectURL(blob);
		frameCount++;
	}
</script>

<div class="relative w-full h-full bg-black">
	{#if imgSrc}
		<!-- MJPEG frame display -->
		<img src={imgSrc} alt="CARLA camera feed"
			class="w-full h-full object-contain" />
	{:else}
		<!-- Placeholder when no frames received yet -->
		<div class="absolute inset-0 flex items-center justify-center">
			<div class="text-center">
				<div class="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-800 flex items-center justify-center">
					<svg class="w-8 h-8 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z" />
					</svg>
				</div>
				<p class="text-sm text-gray-500">Waiting for camera feed...</p>
				<p class="text-xs text-gray-600 mt-1">Frames will appear once driving starts</p>
			</div>
		</div>
	{/if}

	<!-- Camera view toggle buttons - above the HUD -->
	<div class="absolute bottom-16 sm:bottom-20 left-1/2 -translate-x-1/2 flex gap-0.5 sm:gap-1 bg-black/60 rounded-lg p-0.5 sm:p-1 pointer-events-auto">
		{#each CAMERA_VIEWS as view}
			<button
				onclick={() => onSwitchView(view.id as CameraView)}
				class="px-1.5 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs rounded-md transition-colors {activeView === view.id
					? 'bg-white/20 text-white'
					: 'text-gray-400 hover:text-white hover:bg-white/10'}"
			>
				<span class="hidden sm:inline">{view.label}</span><span class="sm:hidden">{view.key}</span>
				<span class="ml-0.5 sm:ml-1 text-gray-500 hidden sm:inline">{view.key}</span>
			</button>
		{/each}
	</div>
</div>

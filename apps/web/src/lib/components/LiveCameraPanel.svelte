<script lang="ts">
	import type { RuntimeConfig } from '$lib/runtime-config';
	import LiveVideoCard from './LiveVideoCard.svelte';

	interface Props {
		config: RuntimeConfig | null;
	}

	let { config }: Props = $props();
</script>

<section class="bg-black">
	{#if config}
		<div
			class="grid gap-px bg-gray-900"
			style="grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));"
		>
			{#each config.videoCameraIds as cameraId}
				<LiveVideoCard {cameraId} />
			{/each}
		</div>
	{:else}
		<div class="flex min-h-40 items-center justify-center bg-black">
			<div class="h-8 w-8 animate-spin rounded-full border-2 border-gray-700 border-t-cyan-300"></div>
		</div>
	{/if}
</section>

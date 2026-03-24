<script lang="ts">
	import type { VehicleTelemetry } from '$lib/types';

	interface Props {
		telemetry: VehicleTelemetry;
		isRecording?: boolean;
	}
	let { telemetry, isRecording = false }: Props = $props();

	let speedPct = $derived(Math.min(telemetry.speed / 120, 1));
	let steerPct = $derived((telemetry.steer + 1) / 2); // 0 to 1
	let throttlePct = $derived(telemetry.throttle);
	let brakePct = $derived(telemetry.brake);
</script>

<div class="absolute inset-0 pointer-events-none select-none">
	<!-- Speed display - bottom center -->
	<div class="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1">
		<span class="text-5xl font-bold text-white tabular-nums drop-shadow-lg">
			{Math.round(telemetry.speed)}
		</span>
		<span class="text-xs text-gray-300 uppercase tracking-widest">km/h</span>
	</div>

	<!-- Gear indicator - bottom center right -->
	<div class="absolute bottom-8 left-1/2 translate-x-20 flex flex-col items-center gap-1">
		<span class="text-2xl font-bold text-gray-400 tabular-nums">
			{telemetry.gear > 0 ? `D${telemetry.gear}` : telemetry.gear === 0 ? 'N' : 'R'}
		</span>
	</div>

	<!-- Steering indicator - bottom -->
	<div class="absolute bottom-28 left-1/2 -translate-x-1/2 w-48">
		<div class="h-1.5 bg-gray-700/60 rounded-full relative">
			<div class="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg transition-all duration-75"
				style="left: {steerPct * 100}%"></div>
			<!-- Center mark -->
			<div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-0.5 h-3 bg-gray-500"></div>
		</div>
	</div>

	<!-- Throttle/Brake bars - bottom right -->
	<div class="absolute bottom-8 right-8 flex gap-2 items-end h-24">
		<!-- Throttle -->
		<div class="flex flex-col items-center gap-1">
			<div class="w-4 h-20 bg-gray-700/60 rounded-full relative overflow-hidden">
				<div class="absolute bottom-0 w-full bg-green-500 rounded-full transition-all duration-75"
					style="height: {throttlePct * 100}%"></div>
			</div>
			<span class="text-[10px] text-gray-400">T</span>
		</div>
		<!-- Brake -->
		<div class="flex flex-col items-center gap-1">
			<div class="w-4 h-20 bg-gray-700/60 rounded-full relative overflow-hidden">
				<div class="absolute bottom-0 w-full bg-red-500 rounded-full transition-all duration-75"
					style="height: {brakePct * 100}%"></div>
			</div>
			<span class="text-[10px] text-gray-400">B</span>
		</div>
	</div>

	<!-- Recording indicator - top right -->
	{#if isRecording}
		<div class="absolute top-4 right-4 flex items-center gap-2">
			<div class="w-3 h-3 bg-red-500 rounded-full animate-pulse"></div>
			<span class="text-xs text-red-400 font-medium">REC</span>
		</div>
	{/if}

	<!-- GPS position - top left -->
	<div class="absolute top-4 left-4 text-xs text-gray-400 font-mono">
		{telemetry.pos[0].toFixed(1)}, {telemetry.pos[1].toFixed(1)}, {telemetry.pos[2].toFixed(1)}
	</div>
</div>

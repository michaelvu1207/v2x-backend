<script lang="ts">
	import type { VehicleTelemetry } from '$lib/types';

	interface Props {
		telemetry: VehicleTelemetry;
		isRecording?: boolean;
	}
	let { telemetry, isRecording = false }: Props = $props();

	let steerPct = $derived((telemetry.steer + 1) / 2);
	let throttlePct = $derived(telemetry.throttle);
	let brakePct = $derived(telemetry.brake);
</script>

<div class="absolute inset-0 pointer-events-none select-none">
	<!-- Bottom HUD bar — always visible, compact on small screens -->
	<div class="absolute bottom-0 inset-x-0 flex items-end justify-center pb-2 sm:pb-4 gap-3 sm:gap-6">
		<!-- Throttle bar -->
		<div class="flex flex-col items-center gap-0.5">
			<div class="w-3 sm:w-4 h-12 sm:h-16 bg-gray-700/60 rounded-full relative overflow-hidden">
				<div class="absolute bottom-0 w-full bg-green-500 rounded-full transition-all duration-75"
					style="height: {throttlePct * 100}%"></div>
			</div>
			<span class="text-[8px] sm:text-[10px] text-gray-400">T</span>
		</div>

		<!-- Steering indicator -->
		<div class="flex flex-col items-center gap-1">
			<div class="w-24 sm:w-36">
				<div class="h-1 sm:h-1.5 bg-gray-700/60 rounded-full relative">
					<div class="absolute top-1/2 -translate-y-1/2 w-2 sm:w-3 h-2 sm:h-3 bg-white rounded-full shadow-lg transition-all duration-75"
						style="left: {steerPct * 100}%"></div>
					<div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-px h-2 bg-gray-500"></div>
				</div>
			</div>

			<!-- Speed + Gear -->
			<div class="flex items-baseline gap-2">
				<span class="text-2xl sm:text-4xl font-bold text-white tabular-nums drop-shadow-lg leading-none">
					{Math.round(telemetry.speed)}
				</span>
				<span class="text-[10px] sm:text-xs text-gray-400">km/h</span>
				<span class="text-sm sm:text-lg font-bold text-gray-500 tabular-nums ml-1">
					{telemetry.gear > 0 ? `D${telemetry.gear}` : telemetry.gear === 0 ? 'N' : 'R'}
				</span>
			</div>
		</div>

		<!-- Brake bar -->
		<div class="flex flex-col items-center gap-0.5">
			<div class="w-3 sm:w-4 h-12 sm:h-16 bg-gray-700/60 rounded-full relative overflow-hidden">
				<div class="absolute bottom-0 w-full bg-red-500 rounded-full transition-all duration-75"
					style="height: {brakePct * 100}%"></div>
			</div>
			<span class="text-[8px] sm:text-[10px] text-gray-400">B</span>
		</div>
	</div>

	<!-- Recording indicator - top right (offset to avoid button overlap) -->
	{#if isRecording}
		<div class="absolute top-12 sm:top-14 right-2 sm:right-4 flex items-center gap-1">
			<div class="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
			<span class="text-[10px] text-red-400 font-medium">REC</span>
		</div>
	{/if}

	<!-- GPS position - top left (offset to avoid button overlap) -->
	<div class="absolute top-12 sm:top-14 left-2 sm:left-4 text-[10px] sm:text-xs text-gray-500 font-mono">
		{telemetry.pos[0].toFixed(1)}, {telemetry.pos[1].toFixed(1)}
	</div>
</div>

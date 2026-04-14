<script lang="ts">
	import { rawAxes, calibration, gamepadConnected, gamepadName, recalibrateRestValues } from '$lib/stores/gamepad';
	import type { GamepadCalibration } from '$lib/types';

	interface Props {
		onComplete: () => void;
	}
	let { onComplete }: Props = $props();

	let step = $state(0); // 0=steer, 1=gas, 2=brake
	let detecting = $state(false);
	let detectedAxis = $state(-1);
	let maxDelta = $state(0);
	let baselineAxes = $state<number[]>([]);
	let result = $state<Partial<GamepadCalibration>>({});

	const steps = [
		{ label: 'Steering', instruction: 'Turn your wheel fully left and right', key: 'steerAxis' as const },
		{ label: 'Gas Pedal', instruction: 'Press your gas pedal fully, then release', key: 'gasAxis' as const },
		{ label: 'Brake Pedal', instruction: 'Press your brake pedal fully, then release', key: 'brakeAxis' as const },
	];

	function startDetection() {
		detecting = true;
		detectedAxis = -1;
		maxDelta = 0;
		baselineAxes = [...$rawAxes];
	}

	// Watch raw axes during detection
	$effect(() => {
		if (!detecting || $rawAxes.length === 0 || baselineAxes.length === 0) return;

		let bestAxis = -1;
		let bestDelta = 0;

		for (let i = 0; i < $rawAxes.length; i++) {
			const delta = Math.abs($rawAxes[i] - baselineAxes[i]);
			if (delta > bestDelta) {
				bestDelta = delta;
				bestAxis = i;
			}
		}

		if (bestDelta > 0.3 && bestDelta > maxDelta) {
			maxDelta = bestDelta;
			detectedAxis = bestAxis;
		}
	});

	function confirmAxis() {
		if (detectedAxis < 0) return;

		const key = steps[step].key;
		result[key] = detectedAxis;

		detecting = false;
		step++;

		if (step >= steps.length) {
			// Save axis assignments without stomping on inversion flags —
			// recalibrateRestValues() will re-derive those from the live
			// hardware state for the newly-assigned pedal axes.
			calibration.update((c) => ({
				...c,
				steerAxis: result.steerAxis ?? c.steerAxis,
				gasAxis: result.gasAxis ?? c.gasAxis,
				brakeAxis: result.brakeAxis ?? c.brakeAxis,
			}));
			recalibrateRestValues();
			onComplete();
		}
	}

	function skipCalibration() {
		onComplete();
	}
</script>

<div class="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
	<div class="bg-gray-900 rounded-2xl p-8 max-w-md w-full mx-4 border border-gray-700">
		<h2 class="text-xl font-bold text-white mb-1">Wheel Calibration</h2>
		<p class="text-sm text-gray-400 mb-6">Step {step + 1} of {steps.length}</p>

		{#if !$gamepadConnected}
			<div class="text-center py-8">
				<p class="text-gray-400 mb-2">No wheel detected</p>
				<p class="text-xs text-gray-500">Connect your Logitech wheel and press a button</p>
			</div>
		{:else}
			<div class="mb-6">
				<p class="text-sm text-gray-300 mb-1">{steps[step].label}</p>
				<p class="text-lg text-white font-medium">{steps[step].instruction}</p>
			</div>

			{#if !detecting}
				<button onclick={startDetection}
					class="w-full py-3 bg-blue-600 hover:bg-blue-500 rounded-lg text-white font-medium transition-colors">
					Start Detection
				</button>
			{:else}
				<div class="mb-4">
					<!-- Live axis display -->
					<div class="grid grid-cols-4 gap-1 mb-4">
						{#each $rawAxes as axis, i}
							<div class="flex flex-col items-center p-2 rounded-lg {detectedAxis === i ? 'bg-blue-600/30 border border-blue-500' : 'bg-gray-800'}">
								<span class="text-[10px] text-gray-500">Axis {i}</span>
								<span class="text-sm font-mono {detectedAxis === i ? 'text-blue-400' : 'text-gray-400'}">{axis.toFixed(2)}</span>
							</div>
						{/each}
					</div>

					{#if detectedAxis >= 0}
						<p class="text-sm text-green-400 mb-3">Detected: Axis {detectedAxis}</p>
						<button onclick={confirmAxis}
							class="w-full py-3 bg-green-600 hover:bg-green-500 rounded-lg text-white font-medium transition-colors">
							Confirm Axis {detectedAxis}
						</button>
					{:else}
						<p class="text-sm text-yellow-400 animate-pulse">Move the control...</p>
					{/if}
				</div>
			{/if}
		{/if}

		<button onclick={skipCalibration}
			class="mt-4 w-full py-2 text-sm text-gray-500 hover:text-gray-300 transition-colors">
			Skip (use defaults)
		</button>
	</div>
</div>

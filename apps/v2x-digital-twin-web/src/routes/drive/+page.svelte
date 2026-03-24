<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { DRIVE_WS_URL } from '$lib/constants';
	import type { CameraView } from '$lib/types';

	import {
		gamepadConnected,
		normalizedInput,
		startPolling,
		stopPolling,
	} from '$lib/stores/gamepad';

	import {
		keyboardActive,
		keyboardInput,
		startKeyboardInput,
		stopKeyboardInput,
	} from '$lib/stores/keyboard';

	import {
		driveConnected,
		sessionState,
		telemetry,
		lastError,
		objectsCount,
		connect,
		disconnect,
		startSession,
		sendControl,
		switchCamera,
		endSession,
		respawnVehicle,
		setOnFrame,
	} from '$lib/stores/driveSocket';

	import CalibrationWizard from '$lib/components/CalibrationWizard.svelte';
	import CameraViewComponent from '$lib/components/CameraView.svelte';
	import HudOverlay from '$lib/components/HudOverlay.svelte';

	type InputMode = 'wheel' | 'keyboard';

	let showCalibration = $state(false);
	let activeCamera = $state<CameraView>('chase');
	let controlLoopId = $state<number | null>(null);
	let inputMode = $state<InputMode>('keyboard');
	let cameraViewRef = $state<CameraViewComponent | null>(null);

	let connected = $derived($driveConnected);
	let state = $derived($sessionState);
	let currentTelemetry = $derived($telemetry);
	let gamepad = $derived($gamepadConnected);
	let error = $derived($lastError);

	$effect(() => {
		if ($sessionState === 'driving') {
			startControlLoop();
		}
	});

	onMount(() => {
		startPolling();
		startKeyboardInput();
		connect(DRIVE_WS_URL);

		setOnFrame((blob: Blob) => {
			if (cameraViewRef) {
				cameraViewRef.pushFrame(blob);
			}
		});
	});

	onDestroy(() => {
		stopControlLoop();
		stopPolling();
		stopKeyboardInput();
		setOnFrame(null);
		if (state === 'driving' || state === 'ready') {
			endSession();
		}
		disconnect();
	});

	function handleQuickStart() {
		const now = new Date();
		const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
		startSession(oneHourAgo.toISOString(), now.toISOString());
	}

	function handleEndSession() {
		stopControlLoop();
		endSession();
	}

	function handleCameraSwitch(view: CameraView) {
		activeCamera = view;
		switchCamera(view);
	}

	function handleCalibrationComplete() {
		showCalibration = false;
	}

	function setInputMode(mode: InputMode) {
		inputMode = mode;
	}

	function startControlLoop() {
		if (controlLoopId !== null) return;
		function loop() {
			const input = inputMode === 'wheel' ? $normalizedInput : $keyboardInput;
			sendControl(input.steer, input.throttle, input.brake, input.reverse);
			controlLoopId = requestAnimationFrame(loop);
		}
		controlLoopId = requestAnimationFrame(loop);
	}

	function stopControlLoop() {
		if (controlLoopId !== null) {
			cancelAnimationFrame(controlLoopId);
			controlLoopId = null;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
		if (e.key === 'Escape' && (state === 'driving' || state === 'ready')) {
			handleEndSession();
		}
		if (e.key === 'r' && state === 'driving') {
			respawnVehicle();
		}
	}
</script>

<svelte:head>
	<title>V2X Drive</title>
</svelte:head>

<svelte:window onkeydown={handleKeydown} />

{#if showCalibration}
	<CalibrationWizard onComplete={handleCalibrationComplete} />
{/if}

<div class="h-screen w-screen bg-black relative overflow-hidden">
	{#if state === 'idle' || state === 'connecting'}
		<div class="absolute inset-0 flex items-center justify-center bg-gray-950">
			<div class="w-80 p-6 bg-gray-900 rounded-2xl border border-gray-800 text-center">
				{#if !connected}
					<div class="py-8">
						<div class="w-8 h-8 mx-auto mb-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
						<p class="text-sm text-gray-400">Connecting to drive server...</p>
					</div>
				{:else}
					<h2 class="text-xl font-bold text-white mb-2">V2X Drive</h2>
					<p class="text-sm text-gray-400 mb-4">Drive through the CARLA world</p>

					<!-- Input mode toggle -->
					<div class="flex justify-center mb-4">
						<div class="flex bg-gray-800 rounded-lg p-0.5">
							<button onclick={() => setInputMode('keyboard')}
								class="px-3 py-1 rounded-md text-sm transition-colors {inputMode === 'keyboard' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-white'}">
								Keyboard
							</button>
							<button onclick={() => setInputMode('wheel')}
								class="px-3 py-1 rounded-md text-sm transition-colors {inputMode === 'wheel' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-white'} {!gamepad ? 'opacity-50' : ''}">
								Wheel {gamepad ? '' : '(N/A)'}
							</button>
						</div>
					</div>

					<button onclick={handleQuickStart}
						class="w-full py-3 bg-green-600 hover:bg-green-500 rounded-xl text-lg font-semibold text-white transition-colors mb-4">
						Start Driving
					</button>

					{#if inputMode === 'keyboard'}
						<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500 text-left">
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">W</kbd> Throttle</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">S</kbd> Reverse</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">A</kbd> / <kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">D</kbd> Steer</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">Space</kbd> Brake</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">R</kbd> Respawn</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">1-4</kbd> Camera</span>
						</div>
					{:else if gamepad}
						<p class="text-xs text-green-400">Wheel connected — ready</p>
					{:else}
						<p class="text-xs text-yellow-400">Connect wheel or switch to Keyboard</p>
					{/if}
				{/if}
			</div>
		</div>

	{:else if state === 'reconstructing'}
		<div class="absolute inset-0 flex items-center justify-center bg-gray-950">
			<div class="text-center">
				<div class="w-12 h-12 mx-auto mb-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
				<p class="text-lg text-white font-medium">Loading scene...</p>
			</div>
		</div>

	{:else if state === 'driving'}
		<!-- Full-screen camera — no header, everything overlays -->
		<CameraViewComponent bind:this={cameraViewRef} activeView={activeCamera} onSwitchView={handleCameraSwitch} />
		<HudOverlay telemetry={currentTelemetry} isRecording={true} />

		<!-- All buttons overlay on the video -->
		<div class="absolute top-2 right-2 z-20 flex gap-1.5 pointer-events-auto">
			{#each [{ id: 'chase', label: 'Chase' }, { id: 'hood', label: 'Hood' }, { id: 'bird', label: 'Bird' }, { id: 'free', label: 'Free' }] as view}
				<button onclick={() => handleCameraSwitch(view.id as CameraView)}
					class="px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors {activeCamera === view.id
						? 'bg-white/25 text-white'
						: 'bg-black/50 hover:bg-black/70 text-gray-300'}">
					{view.label}
				</button>
			{/each}
			<button onclick={() => respawnVehicle()}
				class="px-2.5 py-1.5 bg-blue-600/70 hover:bg-blue-600 rounded-lg text-xs font-medium text-white transition-colors">
				Respawn
			</button>
			<button onclick={handleEndSession}
				class="px-2.5 py-1.5 bg-red-600/70 hover:bg-red-600 rounded-lg text-xs font-medium text-white transition-colors">
				End
			</button>
		</div>

		<!-- Input mode + connection — top left, subtle -->
		<div class="absolute top-2 left-2 z-20 flex items-center gap-2 pointer-events-auto">
			<span class="px-2 py-1 bg-black/50 rounded text-[10px] text-gray-300">
				{inputMode === 'keyboard' ? 'WASD' : 'Wheel'}
			</span>
			<span class="w-1.5 h-1.5 rounded-full {connected ? 'bg-green-500' : 'bg-red-500'}"></span>
		</div>

	{:else if state === 'error'}
		<div class="absolute inset-0 flex items-center justify-center bg-gray-950">
			<div class="text-center max-w-md">
				<p class="text-xl text-red-400 font-bold mb-2">Error</p>
				<p class="text-sm text-gray-400 mb-4">{error}</p>
				<button onclick={() => sessionState.set('idle')}
					class="px-6 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-white transition-colors">
					Try Again
				</button>
			</div>
		</div>
	{/if}
</div>

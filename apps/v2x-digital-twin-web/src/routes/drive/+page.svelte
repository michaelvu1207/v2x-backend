<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { DRIVE_WS_URL } from '$lib/constants';
	import type { CameraView } from '$lib/types';

	// Stores — Gamepad (wheel)
	import {
		gamepadConnected,
		normalizedInput,
		startPolling,
		stopPolling,
	} from '$lib/stores/gamepad';

	// Stores — Keyboard
	import {
		keyboardActive,
		keyboardInput,
		startKeyboardInput,
		stopKeyboardInput,
	} from '$lib/stores/keyboard';

	// Stores — Drive session
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

	// Components
	import TimePicker from '$lib/components/TimePicker.svelte';
	import CalibrationWizard from '$lib/components/CalibrationWizard.svelte';
	import CameraViewComponent from '$lib/components/CameraView.svelte';
	import HudOverlay from '$lib/components/HudOverlay.svelte';

	type InputMode = 'wheel' | 'keyboard';

	let showCalibration = $state(false);
	let activeCamera = $state<CameraView>('chase');
	let controlLoopId = $state<number | null>(null);
	let inputMode = $state<InputMode>('keyboard');
	let cameraViewRef = $state<CameraViewComponent | null>(null);

	// Reactive values from stores
	let connected = $derived($driveConnected);
	let state = $derived($sessionState);
	let currentTelemetry = $derived($telemetry);
	let gamepad = $derived($gamepadConnected);
	let error = $derived($lastError);
	let sceneObjects = $derived($objectsCount);

	// Use whichever input source is active
	let hasAnyInput = $derived(gamepad || true); // keyboard always available

	// Auto-detect: if a wheel connects, suggest switching
	$effect(() => {
		if ($gamepadConnected && inputMode === 'keyboard') {
			// Wheel just connected — user can switch manually
		}
	});

	onMount(() => {
		startPolling(); // always poll for gamepad connections
		startKeyboardInput();
		connect(DRIVE_WS_URL);

		// Wire binary WebSocket frames to the camera view
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

	function handleTimeSelect(start: string, end: string) {
		startSession(start, end);
	}

	function handleStartDriving() {
		startControlLoop();
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

<div class="h-screen w-screen bg-gray-950 flex flex-col">
	<!-- Top bar -->
	<header class="flex items-center justify-between px-4 py-2 bg-gray-900/80 border-b border-gray-800 z-10">
		<div class="flex items-center gap-3">
			<a href="/" class="text-sm text-gray-400 hover:text-white transition-colors">&larr; Dashboard</a>
			<span class="text-white font-semibold">V2X Drive</span>
		</div>
		<div class="flex items-center gap-4 text-xs">
			<!-- Input mode toggle -->
			<div class="flex bg-gray-800 rounded-lg p-0.5">
				<button
					onclick={() => setInputMode('keyboard')}
					class="px-2.5 py-1 rounded-md transition-colors {inputMode === 'keyboard' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-white'}">
					Keyboard
				</button>
				<button
					onclick={() => setInputMode('wheel')}
					class="px-2.5 py-1 rounded-md transition-colors {inputMode === 'wheel' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-white'} {!gamepad ? 'opacity-50' : ''}">
					Wheel {gamepad ? '' : '(N/A)'}
				</button>
			</div>
			<!-- Connection status -->
			<span class="flex items-center gap-1.5">
				<span class="w-2 h-2 rounded-full {connected ? 'bg-green-500' : 'bg-red-500'}"></span>
				{connected ? 'Connected' : 'Disconnected'}
			</span>
			{#if inputMode === 'wheel'}
				<button onclick={() => showCalibration = true}
					class="px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors">
					Calibrate
				</button>
			{/if}
		</div>
	</header>

	<!-- Main content -->
	<div class="flex-1 relative">
		{#if state === 'idle' || state === 'connecting'}
			<!-- Setup panel -->
			<div class="absolute inset-0 flex items-center justify-center">
				<div class="w-[28rem] p-6 bg-gray-900 rounded-2xl border border-gray-800">
					{#if !connected}
						<div class="text-center py-8">
							<div class="w-8 h-8 mx-auto mb-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
							<p class="text-sm text-gray-400">Connecting to drive server...</p>
						</div>
					{:else}
						<TimePicker onselect={handleTimeSelect} disabled={!connected} />

						<!-- Controls reference -->
						<div class="mt-4 pt-4 border-t border-gray-800">
							{#if inputMode === 'keyboard'}
								<p class="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Keyboard Controls</p>
								<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-400">
									<span><kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">W</kbd> / <kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">↑</kbd> Throttle</span>
									<span><kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">S</kbd> / <kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">↓</kbd> Reverse</span>
									<span><kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">A</kbd> / <kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">←</kbd> Steer left</span>
									<span><kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">D</kbd> / <kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">→</kbd> Steer right</span>
									<span><kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">Space</kbd> Brake</span>
									<span><kbd class="px-1.5 py-0.5 bg-gray-800 rounded text-gray-300 font-mono">1-4</kbd> Camera views</span>
								</div>
							{:else}
								<p class="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Wheel Controls</p>
								{#if gamepad}
									<p class="text-xs text-green-400">Wheel connected — ready to drive</p>
								{:else}
									<p class="text-xs text-yellow-400">Connect your steering wheel to use wheel mode</p>
								{/if}
							{/if}
						</div>
					{/if}
				</div>
			</div>

		{:else if state === 'reconstructing'}
			<div class="absolute inset-0 flex items-center justify-center">
				<div class="text-center">
					<div class="w-12 h-12 mx-auto mb-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
					<p class="text-lg text-white font-medium">Reconstructing Scene</p>
					<p class="text-sm text-gray-400 mt-1">Spawning objects in CARLA...</p>
				</div>
			</div>

		{:else if state === 'ready'}
			<div class="absolute inset-0 flex items-center justify-center">
				<div class="text-center">
					<p class="text-2xl text-white font-bold mb-2">Scene Ready</p>
					<p class="text-sm text-gray-400 mb-2">{sceneObjects} objects reconstructed</p>
					<p class="text-xs text-gray-500 mb-6">
						{inputMode === 'keyboard' ? 'Using keyboard controls (WASD)' : 'Using steering wheel'}
					</p>
					<button onclick={handleStartDriving}
						class="px-8 py-3 bg-green-600 hover:bg-green-500 rounded-xl text-lg font-semibold text-white transition-colors">
						Start Driving
					</button>
				</div>
			</div>

		{:else if state === 'driving'}
			<!-- Full-screen camera view with HUD -->
			<CameraViewComponent bind:this={cameraViewRef} activeView={activeCamera} onSwitchView={handleCameraSwitch} />
			<HudOverlay telemetry={currentTelemetry} isRecording={true} />

			<!-- Input mode indicator -->
			<div class="absolute top-4 left-4 z-20 px-3 py-1.5 bg-black/60 rounded-lg text-xs text-gray-300 pointer-events-none">
				{inputMode === 'keyboard' ? 'WASD' : 'Wheel'}
			</div>

			<!-- Top-right buttons -->
			<div class="absolute top-4 right-4 z-20 flex gap-2 pointer-events-auto">
				<button onclick={() => respawnVehicle()}
					class="px-4 py-2 bg-blue-600/80 hover:bg-blue-600 rounded-lg text-sm font-medium text-white transition-colors">
					Respawn (R)
				</button>
				<button onclick={handleEndSession}
					class="px-4 py-2 bg-red-600/80 hover:bg-red-600 rounded-lg text-sm font-medium text-white transition-colors">
					End Session (Esc)
				</button>
			</div>

		{:else if state === 'error'}
			<div class="absolute inset-0 flex items-center justify-center">
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
</div>

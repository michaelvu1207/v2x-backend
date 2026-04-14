<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { DRIVE_TUNNELS, type TunnelId } from '$lib/constants';
	import type { CameraView } from '$lib/types';

	import {
		gamepadConnected,
		calibrated,
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
		vehicleList,
		spawnableObjects,
		placedCount,
		scenarioList,
		v2xSignalCount,
		connect,
		disconnect,
		startSession,
		sendControl,
		switchCamera,
		endSession,
		respawnVehicle,
		requestVehicles,
		requestObjects,
		requestScenarios,
		saveScenario,
		loadScenario,
		spawnObject,
		undoPlace,
		undoV2xSignal,
		setOnFrame,
	} from '$lib/stores/driveSocket';

	import CalibrationWizard from '$lib/components/CalibrationWizard.svelte';
	import CameraViewComponent from '$lib/components/CameraView.svelte';
	import HudOverlay from '$lib/components/HudOverlay.svelte';
	import V2xToast from '$lib/components/V2xToast.svelte';
	import V2xSignalPlacer from '$lib/components/V2xSignalPlacer.svelte';

	type InputMode = 'wheel' | 'keyboard';

	let showCalibration = $state(false);
	let activeCamera = $state<CameraView>('chase');
	let controlLoopId = $state<number | null>(null);
	let inputMode = $state<InputMode>('keyboard');
	let cameraViewRef = $state<CameraViewComponent | null>(null);
	let selectedTunnel = $state<TunnelId>(DRIVE_TUNNELS[0].id);
	let selectedVehicle = $state('vehicle.tesla.model3');
	let showObjectPlacer = $state(false);
	let showV2xPlacer = $state(false);
	let objectFilter = $state('');
	let selectedScenario = $state('');
	let showSaveDialog = $state(false);
	let scenarioName = $state('');

	let vehicles = $derived($vehicleList);
	let objects = $derived($spawnableObjects);
	let scenarios = $derived($scenarioList);
	let numPlaced = $derived($placedCount);
	let numV2xSignals = $derived($v2xSignalCount);
	let filteredObjects = $derived(
		objects.filter(o =>
			objectFilter === '' ||
			o.name.toLowerCase().includes(objectFilter.toLowerCase()) ||
			o.id.toLowerCase().includes(objectFilter.toLowerCase())
		)
	);

	function getSelectedUrl(): string {
		return DRIVE_TUNNELS.find(t => t.id === selectedTunnel)?.url ?? DRIVE_TUNNELS[0].url;
	}

	function switchTunnel(id: TunnelId) {
		if (id === selectedTunnel) return;
		selectedTunnel = id;
		// Reconnect with the new URL — clear vehicle list so it re-fetches
		vehicleList.set([]);
		disconnect();
		connect(getSelectedUrl());
	}

	let connected = $derived($driveConnected);
	let state = $derived($sessionState);
	let currentTelemetry = $derived($telemetry);
	let gamepad = $derived($gamepadConnected);
	let isCalibrated = $derived($calibrated);
	let wheelReady = $derived(inputMode === 'keyboard' || isCalibrated);
	let error = $derived($lastError);

	$effect(() => {
		if ($sessionState === 'driving') {
			startControlLoop();
		}
	});

	function cleanupSession() {
		stopControlLoop();
		stopPolling();
		stopKeyboardInput();
		setOnFrame(null);
		if (state === 'driving' || state === 'ready' || state === 'reconstructing') {
			endSession();
		}
		disconnect();
	}

	// Request vehicle list and scenarios once connected
	$effect(() => {
		if ($driveConnected && $vehicleList.length === 0) {
			requestVehicles();
			requestScenarios();
		}
	});

	onMount(() => {
		startPolling();
		startKeyboardInput();
		connect(getSelectedUrl());

		setOnFrame((blob: Blob) => {
			if (cameraViewRef) {
				cameraViewRef.pushFrame(blob);
			}
		});
	});

	onDestroy(() => {
		cleanupSession();
	});

	// Auto-load scenario when session becomes driving
	$effect(() => {
		if ($sessionState === 'driving' && selectedScenario) {
			loadScenario(selectedScenario);
			selectedScenario = '';
		}
	});

	function handleQuickStart() {
		const now = new Date();
		const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
		startSession(oneHourAgo.toISOString(), now.toISOString(), selectedVehicle);
	}

	function handleSaveScenario() {
		const name = scenarioName.trim();
		if (!name) return;
		saveScenario(name);
		scenarioName = '';
		showSaveDialog = false;
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
		if (e.key === 'Escape') {
			if (showObjectPlacer) {
				showObjectPlacer = false;
			} else if (showV2xPlacer) {
				showV2xPlacer = false;
			} else if (state === 'driving' || state === 'ready') {
				handleEndSession();
			}
		}
		if (state !== 'driving') return;
		if (e.key === 'r') {
			respawnVehicle();
		}
		if (e.key === 'p' || e.key === 'P') {
			showObjectPlacer = !showObjectPlacer;
			showV2xPlacer = false;
			if (showObjectPlacer && objects.length === 0) {
				requestObjects();
			}
		}
		if (e.key === 'v' || e.key === 'V') {
			showV2xPlacer = !showV2xPlacer;
			showObjectPlacer = false;
		}
		if ((e.key === 'u' || e.key === 'U') && !showObjectPlacer && !showV2xPlacer) {
			undoPlace();
		}
	}
</script>

<svelte:head>
	<title>V2X Drive</title>
</svelte:head>

<svelte:window onkeydown={handleKeydown} onbeforeunload={cleanupSession} />

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
					<div class="flex justify-center mb-3">
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
						{#if inputMode === 'wheel' && gamepad}
							<button onclick={() => showCalibration = true}
								class="ml-2 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-white bg-gray-800 transition-colors">
								Calibrate
							</button>
						{/if}
					</div>

					<!-- Tunnel selector -->
					<div class="flex justify-center mb-3">
						<div class="flex bg-gray-800 rounded-lg p-0.5">
							{#each DRIVE_TUNNELS as tunnel}
								<button onclick={() => switchTunnel(tunnel.id)}
									class="px-3 py-1 rounded-md text-sm transition-colors {selectedTunnel === tunnel.id ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-white'}">
									{tunnel.label}
								</button>
							{/each}
						</div>
					</div>

					<!-- Vehicle picker -->
					<div class="mb-4">
						{#if vehicles.length > 0}
							<select
								bind:value={selectedVehicle}
								class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 appearance-none cursor-pointer"
							>
								{#each vehicles as v}
									<option value={v.id}>
										{v.name}{v.wheels === 2 ? ' (bike)' : ''}
									</option>
								{/each}
							</select>
						{:else}
							<div class="px-3 py-2 bg-gray-800 rounded-lg text-sm text-gray-500 text-center">
								Loading vehicles...
							</div>
						{/if}
					</div>

					<!-- Scenario preset -->
					{#if scenarios.length > 0}
						<div class="mb-3">
							<select
								bind:value={selectedScenario}
								class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 appearance-none cursor-pointer"
							>
								<option value="">No scenario (empty world)</option>
								{#each scenarios as s}
									<option value={s.file}>
										{s.name} ({s.object_count} objects)
									</option>
								{/each}
							</select>
						</div>
					{/if}

					{#if inputMode === 'wheel' && !isCalibrated}
						<button onclick={() => showCalibration = true}
							class="w-full py-3 bg-blue-600 hover:bg-blue-500 rounded-xl text-lg font-semibold text-white transition-colors mb-4">
							Calibrate Wheel
						</button>
						<p class="text-xs text-yellow-400">Calibration required before driving with wheel</p>
					{:else}
						<button onclick={handleQuickStart}
							class="w-full py-3 bg-green-600 hover:bg-green-500 rounded-xl text-lg font-semibold text-white transition-colors mb-4">
							Start Driving
						</button>
					{/if}

					{#if inputMode === 'keyboard'}
						<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500 text-left">
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">W</kbd> Throttle</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">S</kbd> Reverse</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">A</kbd> / <kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">D</kbd> Steer</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">Space</kbd> Brake</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">R</kbd> Respawn</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">1-4</kbd> Camera</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">P</kbd> Place Object</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">V</kbd> V2X Signal</span>
							<span><kbd class="px-1 py-0.5 bg-gray-800 rounded text-gray-400 font-mono">U</kbd> Undo Place</span>
						</div>
					{:else if gamepad && isCalibrated}
						<p class="text-xs text-green-400">Wheel calibrated — ready</p>
					{:else if gamepad}
						<p class="text-xs text-yellow-400">Calibrate wheel to continue</p>
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

		<!-- V2X toast notifications -->
		<V2xToast />

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

		<!-- Input mode + tunnel + connection — top left, subtle -->
		<div class="absolute top-2 left-2 z-20 flex items-center gap-2 pointer-events-auto">
			<span class="px-2 py-1 bg-black/50 rounded text-[10px] text-gray-300">
				{inputMode === 'keyboard' ? 'WASD' : 'Wheel'}
			</span>
			{#if inputMode === 'wheel' && gamepad}
				<button onclick={() => showCalibration = true}
					class="px-2 py-1 bg-black/50 hover:bg-black/70 rounded text-[10px] text-gray-400 hover:text-white transition-colors">
					Calibrate
				</button>
			{/if}
			<span class="px-2 py-1 bg-black/50 rounded text-[10px] text-gray-300">
				{DRIVE_TUNNELS.find(t => t.id === selectedTunnel)?.label}
			</span>
			<span class="w-1.5 h-1.5 rounded-full {connected ? 'bg-green-500' : 'bg-red-500'}"></span>
			{#if numPlaced > 0}
				<span class="px-2 py-1 bg-black/50 rounded text-[10px] text-yellow-300">
					{numPlaced} placed
				</span>
			{/if}
			{#if numV2xSignals > 0}
				<span class="px-2 py-1 bg-black/50 rounded text-[10px] text-cyan-300">
					{numV2xSignals} signals
				</span>
			{/if}
		</div>

		<!-- V2X Signal Placer Panel -->
		{#if showV2xPlacer}
			<V2xSignalPlacer onClose={() => { showV2xPlacer = false; }} />
		{/if}

		<!-- Object Placer Panel — slide-in from bottom-left -->
		{#if showObjectPlacer}
			<div class="absolute bottom-16 left-2 z-30 w-72 max-h-80 bg-gray-900/95 border border-gray-700 rounded-xl overflow-hidden pointer-events-auto flex flex-col">
				<div class="p-2 border-b border-gray-700 flex items-center gap-2">
					<input
						type="text"
						bind:value={objectFilter}
						placeholder="Search objects..."
						class="flex-1 px-2 py-1 bg-gray-800 border border-gray-600 rounded text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
					/>
					<button onclick={() => undoPlace()}
						class="px-2 py-1 bg-yellow-600/70 hover:bg-yellow-600 rounded text-xs text-white"
						title="Undo last (U)">
						Undo
					</button>
					<button onclick={() => { showObjectPlacer = false; }}
						class="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300">
						X
					</button>
				</div>
				<div class="overflow-y-auto flex-1">
					{#each filteredObjects as obj}
						<button
							onclick={() => { spawnObject(obj.id); }}
							class="w-full px-3 py-1.5 text-left text-xs hover:bg-gray-800 transition-colors flex items-center gap-2"
						>
							<span class="w-1.5 h-1.5 rounded-full {obj.category === 'vehicle' ? 'bg-blue-400' : 'bg-orange-400'}"></span>
							<span class="text-white truncate">{obj.name}</span>
							<span class="text-gray-500 text-[10px] ml-auto">{obj.category}</span>
						</button>
					{/each}
					{#if filteredObjects.length === 0}
						<p class="p-3 text-xs text-gray-500 text-center">
							{objects.length === 0 ? 'Loading...' : 'No matches'}
						</p>
					{/if}
				</div>
				<div class="p-1.5 border-t border-gray-700">
					{#if showSaveDialog}
						<div class="flex gap-1">
							<input
								type="text"
								bind:value={scenarioName}
								placeholder="Scenario name..."
								class="flex-1 px-2 py-1 bg-gray-800 border border-gray-600 rounded text-xs text-white placeholder-gray-500 focus:outline-none"
								onkeydown={(e) => { if (e.key === 'Enter') handleSaveScenario(); if (e.key === 'Escape') showSaveDialog = false; }}
							/>
							<button onclick={handleSaveScenario}
								class="px-2 py-1 bg-green-600/70 hover:bg-green-600 rounded text-xs text-white">
								Save
							</button>
						</div>
					{:else}
						<div class="flex items-center justify-between">
							<span class="text-[10px] text-gray-500">P toggle | Click to place | U undo</span>
							{#if numPlaced > 0}
								<button onclick={() => { showSaveDialog = true; }}
									class="px-2 py-0.5 bg-green-600/50 hover:bg-green-600 rounded text-[10px] text-white">
									Save Scene
								</button>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		{/if}

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

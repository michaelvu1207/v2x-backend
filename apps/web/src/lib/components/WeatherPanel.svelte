<script lang="ts">
	import { setWeather } from '$lib/stores/driveSocket';

	interface Props {
		onClose: () => void;
	}

	let { onClose }: Props = $props();

	// Weather parameters
	let cloudiness = $state(5);
	let precipitation = $state(0);
	let precipitationDeposits = $state(0);
	let windIntensity = $state(10);
	let sunAzimuth = $state(45);
	let sunAltitude = $state(45);
	let fogDensity = $state(2);
	let fogDistance = $state(0.75);
	let fogFalloff = $state(0.1);
	let wetness = $state(0);
	let scatteringIntensity = $state(1);
	let mieScattering = $state(0.03);
	let rayleighScattering = $state(0.0331);
	let dustStorm = $state(0);

	const PRESETS: Record<string, () => void> = {
		'Clear Noon': () => {
			cloudiness = 5; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 10; sunAzimuth = -1; sunAltitude = 45;
			fogDensity = 2; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 0; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Clear Sunset': () => {
			cloudiness = 5; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 10; sunAzimuth = -1; sunAltitude = 15;
			fogDensity = 2; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 0; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Clear Night': () => {
			cloudiness = 5; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 10; sunAzimuth = -1; sunAltitude = -90;
			fogDensity = 60; fogDistance = 75; fogFalloff = 1;
			wetness = 0; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Cloudy Noon': () => {
			cloudiness = 60; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 10; sunAzimuth = -1; sunAltitude = 45;
			fogDensity = 3; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 0; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Rainy': () => {
			cloudiness = 80; precipitation = 60; precipitationDeposits = 60;
			windIntensity = 60; sunAzimuth = -1; sunAltitude = 45;
			fogDensity = 3; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 80; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Heavy Rain': () => {
			cloudiness = 100; precipitation = 100; precipitationDeposits = 90;
			windIntensity = 100; sunAzimuth = -1; sunAltitude = 45;
			fogDensity = 7; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 100; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Foggy': () => {
			cloudiness = 40; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 5; sunAzimuth = -1; sunAltitude = 45;
			fogDensity = 70; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 0; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
		'Dust Storm': () => {
			cloudiness = 100; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 100; sunAzimuth = -1; sunAltitude = 45;
			fogDensity = 2; fogDistance = 0.75; fogFalloff = 0.1;
			wetness = 0; scatteringIntensity = 1; mieScattering = 0.03;
			rayleighScattering = 0.0331; dustStorm = 100;
		},
		'No Bloom': () => {
			cloudiness = 0; precipitation = 0; precipitationDeposits = 0;
			windIntensity = 0; sunAzimuth = 45; sunAltitude = 45;
			fogDensity = 0; fogDistance = 0; fogFalloff = 0;
			wetness = 0; scatteringIntensity = 0; mieScattering = 0;
			rayleighScattering = 0.0331; dustStorm = 0;
		},
	};

	function applyPreset(name: string) {
		PRESETS[name]();
		apply();
	}

	function apply() {
		setWeather({
			cloudiness, precipitation, precipitation_deposits: precipitationDeposits,
			wind_intensity: windIntensity, sun_azimuth_angle: sunAzimuth,
			sun_altitude_angle: sunAltitude, fog_density: fogDensity,
			fog_distance: fogDistance, fog_falloff: fogFalloff,
			wetness, scattering_intensity: scatteringIntensity,
			mie_scattering_scale: mieScattering,
			rayleigh_scattering_scale: rayleighScattering, dust_storm: dustStorm,
		});
	}

	type SliderDef = { label: string; get: () => number; set: (v: number) => void; min: number; max: number; step: number };

	const sliders: SliderDef[] = [
		{ label: 'Sun Altitude', get: () => sunAltitude, set: (v) => sunAltitude = v, min: -90, max: 90, step: 1 },
		{ label: 'Sun Azimuth', get: () => sunAzimuth, set: (v) => sunAzimuth = v, min: -1, max: 360, step: 1 },
		{ label: 'Cloudiness', get: () => cloudiness, set: (v) => cloudiness = v, min: 0, max: 100, step: 1 },
		{ label: 'Precipitation', get: () => precipitation, set: (v) => precipitation = v, min: 0, max: 100, step: 1 },
		{ label: 'Puddles', get: () => precipitationDeposits, set: (v) => precipitationDeposits = v, min: 0, max: 100, step: 1 },
		{ label: 'Wind', get: () => windIntensity, set: (v) => windIntensity = v, min: 0, max: 100, step: 1 },
		{ label: 'Fog Density', get: () => fogDensity, set: (v) => fogDensity = v, min: 0, max: 100, step: 1 },
		{ label: 'Fog Distance', get: () => fogDistance, set: (v) => fogDistance = v, min: 0, max: 100, step: 0.25 },
		{ label: 'Fog Falloff', get: () => fogFalloff, set: (v) => fogFalloff = v, min: 0, max: 5, step: 0.1 },
		{ label: 'Wetness', get: () => wetness, set: (v) => wetness = v, min: 0, max: 100, step: 1 },
		{ label: 'Scattering', get: () => scatteringIntensity, set: (v) => scatteringIntensity = v, min: 0, max: 5, step: 0.1 },
		{ label: 'Mie Scatter', get: () => mieScattering, set: (v) => mieScattering = v, min: 0, max: 1, step: 0.01 },
		{ label: 'Rayleigh', get: () => rayleighScattering, set: (v) => rayleighScattering = v, min: 0, max: 0.1, step: 0.001 },
		{ label: 'Dust Storm', get: () => dustStorm, set: (v) => dustStorm = v, min: 0, max: 100, step: 1 },
	];
</script>

<div class="absolute bottom-16 right-2 z-30 w-72 max-h-[70vh] bg-gray-900/95 border border-gray-700 rounded-xl overflow-hidden pointer-events-auto flex flex-col">
	<!-- Header -->
	<div class="p-2.5 border-b border-gray-700 flex items-center justify-between">
		<span class="text-xs font-semibold text-white tracking-wider uppercase">Weather</span>
		<button onclick={onClose}
			class="px-2 py-0.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300">
			X
		</button>
	</div>

	<!-- Presets -->
	<div class="p-2 border-b border-gray-800 flex flex-wrap gap-1">
		{#each Object.keys(PRESETS) as name}
			<button
				onclick={() => applyPreset(name)}
				class="px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-[10px] text-gray-300 hover:text-white transition-colors"
			>
				{name}
			</button>
		{/each}
	</div>

	<!-- Sliders -->
	<div class="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
		{#each sliders as s}
			<div>
				<div class="flex justify-between mb-0.5">
					<label class="text-[10px] text-gray-500">{s.label}</label>
					<span class="text-[10px] text-gray-400 font-mono">{s.get().toFixed(s.step < 1 ? 2 : 0)}</span>
				</div>
				<input
					type="range"
					min={s.min} max={s.max} step={s.step}
					value={s.get()}
					oninput={(e) => { s.set(Number((e.target as HTMLInputElement).value)); }}
					class="w-full h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
				/>
			</div>
		{/each}
	</div>

	<!-- Apply button -->
	<div class="p-2 border-t border-gray-700">
		<button
			onclick={apply}
			class="w-full py-1.5 bg-cyan-600 hover:bg-cyan-500 rounded-lg text-xs font-medium text-white transition-colors"
		>
			Apply Weather
		</button>
	</div>
</div>

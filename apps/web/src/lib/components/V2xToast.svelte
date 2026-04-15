<script lang="ts">
	import { v2xAlerts } from '$lib/stores/driveSocket';
	import { activeZoneAlerts } from '$lib/stores/v2xZones';
	import { onDestroy } from 'svelte';

	// Auto-dismiss alerts after 5 seconds using _uid as key
	const timers = new Map<number, ReturnType<typeof setTimeout>>();

	$effect(() => {
		for (const alert of $v2xAlerts) {
			const uid = (alert as any)._uid;
			if (uid && !timers.has(uid)) {
				timers.set(uid, setTimeout(() => {
					v2xAlerts.update(list => list.filter(a => (a as any)._uid !== uid));
					timers.delete(uid);
				}, 5000));
			}
		}
	});

	onDestroy(() => {
		for (const timer of timers.values()) clearTimeout(timer);
		timers.clear();
	});

	function dismiss(alert: any) {
		v2xAlerts.update(list => list.filter(a => (a as any)._uid !== alert._uid));
	}

	function typeColor(type: string): string {
		switch (type) {
			case 'warning': return 'bg-red-600/90 border-red-400';
			case 'alert': return 'bg-orange-600/90 border-orange-400';
			case 'info': return 'bg-blue-600/90 border-blue-400';
			default: return 'bg-gray-600/90 border-gray-400';
		}
	}

	function typeIcon(type: string): string {
		switch (type) {
			case 'warning': return '\u26A0';
			case 'alert': return '\uD83D\uDEA8';
			case 'info': return '\u2139';
			default: return '\uD83D\uDCE1';
		}
	}

	function typeLabel(type: string): string {
		switch (type) {
			case 'warning': return 'V2X WARNING';
			case 'alert': return 'V2X ALERT';
			case 'info': return 'V2X INFO';
			default: return 'V2X SIGNAL';
		}
	}
</script>

{#if $v2xAlerts.length > 0 || $activeZoneAlerts.length > 0}
	<div class="absolute top-14 right-2 z-40 flex flex-col gap-2 pointer-events-auto max-w-xs">
		<!-- Persistent zone alerts (show while inside, disappear on exit) -->
		{#each $activeZoneAlerts as entry (entry.zone.id)}
			<div class="rounded-lg border-l-4 px-3 py-2 shadow-lg backdrop-blur-sm animate-slide-in {typeColor(entry.zone.signal_type)}">
				<div class="flex items-start gap-2">
					<span class="text-lg leading-none">{typeIcon(entry.zone.signal_type)}</span>
					<div class="flex-1 min-w-0">
						<p class="text-[10px] font-bold text-white/70 uppercase tracking-wide">{typeLabel(entry.zone.signal_type)} ZONE</p>
						<p class="text-sm font-medium text-white leading-tight">{entry.zone.message || entry.zone.name}</p>
					</div>
				</div>
			</div>
		{/each}

		<!-- Server-side V2X alerts (auto-dismiss after 5s) -->
		{#each $v2xAlerts as alert ((alert as any)._uid)}
			<div class="rounded-lg border-l-4 px-3 py-2 shadow-lg backdrop-blur-sm animate-slide-in {typeColor(alert.signal_type)}">
				<div class="flex items-start gap-2">
					<span class="text-lg leading-none">{typeIcon(alert.signal_type)}</span>
					<div class="flex-1 min-w-0">
						<p class="text-[10px] font-bold text-white/70 uppercase tracking-wide">{typeLabel(alert.signal_type)}</p>
						<p class="text-sm font-medium text-white leading-tight">{alert.message}</p>
						<p class="text-[10px] text-white/50 mt-0.5">{alert.distance}m away</p>
					</div>
					<button onclick={() => dismiss(alert)}
						class="text-white/50 hover:text-white text-xs leading-none p-1">
						✕
					</button>
				</div>
			</div>
		{/each}
	</div>
{/if}

<style>
	@keyframes slide-in {
		from { opacity: 0; transform: translateX(100px); }
		to { opacity: 1; transform: translateX(0); }
	}
	:global(.animate-slide-in) {
		animation: slide-in 0.3s ease-out;
	}
</style>

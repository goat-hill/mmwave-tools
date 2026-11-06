<script lang="ts" module>
  export type View = 'xy' | 'yz' | 'range' | 'rd' | 'speed' | 'temps'

  export const VIEWS: Record<View, string> = {
    xy: 'Top view (X-Y)',
    yz: 'Side view (Y-Z)',
    range: 'Range profile',
    rd: 'Range-Doppler heatmap',
    speed: 'Speed vs time',
    temps: 'Temperatures',
  }
</script>

<script lang="ts">
  import Heatmap from './Heatmap.svelte'
  import LinePlot from './LinePlot.svelte'
  import ScatterPlot from './ScatterPlot.svelte'
  import { radar } from './radar.svelte'

  interface Props {
    view: View
    viewRange: number
    colorBy: 'velocity' | 'snr'
    persist: number
  }

  let { view = $bindable(), viewRange, colorBy, persist }: Props = $props()

  const info = $derived(radar.info)
  const latest = $derived(radar.frames.at(-1) ?? null)
  const velMax = $derived(radar.velMax)
  const snrDomain: [number, number] = [10, 40]

  const rangeData = $derived.by(() => {
    const rp = latest?.rangeProfile
    if (!rp) return null
    const step = info?.range_resolution_m ?? 1
    return [rp.map((_, i) => i * step), rp] as [number[], number[]]
  })

  const stats = $derived(latest?.stats ?? null)
  const peakSpeed = $derived(
    radar.speeds[1].reduce<number>((m, v) => (v != null && Math.abs(v) > m ? Math.abs(v) : m), 0),
  )
  const powerMeasured = $derived(stats?.powerMw.some((p) => p != null && p > 0) ?? false)
</script>

<article>
  <header>
    <select bind:value={view} aria-label="Plot">
      {#each Object.entries(VIEWS) as [k, label] (k)}
        <option value={k}>{label}</option>
      {/each}
    </select>
    {#if view === 'xy' || view === 'yz'}
      <span class="note num">{latest?.points.length ?? 0} points</span>
    {:else if view === 'speed'}
      <span class="note num">peak {peakSpeed.toFixed(1)} m/s (last 60 s)</span>
    {:else if view === 'temps' && stats}
      <span class="note num">
        processing {stats.procUs} µs · UART {stats.uartUs} µs{powerMeasured ? '' : ' · power n/a on USB'}
      </span>
    {/if}
  </header>
  <div class="body">
    {#if view === 'xy'}
      <ScatterPlot
        frames={radar.frames}
        {persist}
        xIdx={0}
        yIdx={1}
        xDomain={[-viewRange, viewRange]}
        yDomain={[0, viewRange]}
        xLabel="x (m)"
        yLabel="y (m)"
        {colorBy}
        {velMax}
        {snrDomain}
        fovDeg={60}
      />
    {:else if view === 'yz'}
      <ScatterPlot
        frames={radar.frames}
        {persist}
        xIdx={1}
        yIdx={2}
        xDomain={[0, viewRange]}
        yDomain={[-viewRange / 2, viewRange / 2]}
        xLabel="y (m)"
        yLabel="z (m)"
        {colorBy}
        {velMax}
        {snrDomain}
      />
    {:else if view === 'range'}
      {#if rangeData}
        <LinePlot
          data={rangeData}
          series={[{ label: 'Power', color: '--series-1', unit: 'dB' }]}
          xLabel={info ? 'range (m)' : 'range bin'}
          xUnit={info ? 'm' : ''}
          yLabel="power (dB, relative)"
        />
      {:else if !latest}
        <p class="empty">Waiting for frames. Connect the board, or replay a log.</p>
      {:else}
        <p class="empty">No range profile in the stream. Set the 2nd <code>guiMonitor</code> field to 1.</p>
      {/if}
    {:else if view === 'rd'}
      {#if latest?.rangeDoppler}
        <Heatmap
          rd={latest.rangeDoppler}
          rangeRes={info?.range_resolution_m ?? null}
          velRes={info?.velocity_resolution_mps ?? null}
        />
      {:else if !latest}
        <p class="empty">Waiting for frames. Connect the board, or replay a log.</p>
      {:else}
        <p class="empty">
          No heatmap in the stream. Set the 5th <code>guiMonitor</code> field to 1 (e.g. <code>guiMonitor 1 1 0 0 1 1</code>);
          it adds ~4 KB per frame on the 1.25 Mbaud UART.
        </p>
      {/if}
    {:else if view === 'speed'}
      {#if radar.speeds[0].length > 1}
        <LinePlot
          data={radar.speeds as [number[], ...(number | null)[][]]}
          series={[{ label: 'Fastest point', color: '--series-1', unit: 'm/s', digits: 2 }]}
          xLabel="time (s)"
          xUnit="s"
          xDigits={1}
          yLabel="velocity (m/s, + away)"
        />
      {:else}
        <p class="empty">Waiting for frames. Connect the board, or replay a log.</p>
      {/if}
    {:else if view === 'temps'}
      {#if radar.temps[0].length > 1}
        <LinePlot
          data={radar.temps as [number[], ...number[][]]}
          series={[
            { label: 'Rx avg', color: '--series-1', unit: '°C', digits: 0 },
            { label: 'Tx avg', color: '--series-2', unit: '°C', digits: 0 },
            { label: 'PM', color: '--series-3', unit: '°C', digits: 0 },
            { label: 'Digital', color: '--series-4', unit: '°C', digits: 0 },
          ]}
          xLabel="time (s)"
          xUnit="s"
          xDigits={1}
          yLabel="°C"
        />
      {:else if !latest}
        <p class="empty">Waiting for frames. Connect the board, or replay a log.</p>
      {:else if stats}
        <p class="empty">Collecting temperature samples…</p>
      {:else}
        <p class="empty">No stats yet. Set the 6th <code>guiMonitor</code> field to 1.</p>
      {/if}
    {/if}
  </div>
</article>

<style>
  article {
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    min-height: 0;
    min-width: 0;
  }
  header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px 0;
  }
  header select {
    font-weight: 600;
    border-color: transparent;
    background: transparent;
    padding-left: 0;
  }
  .note {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .body {
    position: relative;
    flex: 1;
    min-height: 0;
    margin: 4px 6px 6px;
  }
  .empty {
    color: var(--text-secondary);
    font-size: 13px;
    padding: 24px;
    max-width: 44ch;
  }
</style>

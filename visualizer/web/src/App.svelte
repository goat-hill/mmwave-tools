<script lang="ts">
  import { onMount } from 'svelte'
  import CliConsole from './lib/CliConsole.svelte'
  import ConfigPanel from './lib/ConfigPanel.svelte'
  import PlotPanel, { type View } from './lib/PlotPanel.svelte'
  import RecordReplay from './lib/RecordReplay.svelte'
  import { gradientCss, isDark, onThemeChange } from './lib/colors'
  import { radar } from './lib/radar.svelte'

  let views = $state<View[]>(['xy', 'yz', 'range', 'temps'])
  let viewRange = $state(3)
  let colorBy = $state<'velocity' | 'snr'>('velocity')
  let persist = $state(3)
  let dark = $state(false)

  const s = $derived(radar.status)
  const latest = $derived(radar.latest)
  const versionMismatch = $derived(
    s?.deviceVersion && s?.sdkVersion && s.deviceVersion !== s.sdkVersion && latest?.source === 'live',
  )
  const velMax = $derived(radar.velMax)

  onMount(() => {
    radar.connect()
    dark = isDark()
    return onThemeChange(() => (dark = isDark()))
  })

  function toggleConnect() {
    radar.send({ type: s?.connected ? 'disconnect' : 'connect' })
  }
</script>

<div class="app">
  <header class="top">
    <h1>mmWave Viewer</h1>

    <div class="conn">
      <span
        class="pill"
        class:ok={radar.socketOpen && s?.connected}
        class:warn={radar.socketOpen && !s?.connected}
      >
        <span class="dot" aria-hidden="true"></span>
        {#if !radar.socketOpen}
          Backend offline
        {:else if s?.replaying}
          Replaying {s.replaying}
        {:else if s?.connected}
          {s.cliPort} · {s.dataPort}
        {:else}
          Board not connected
        {/if}
      </span>
      <button onclick={toggleConnect} disabled={!radar.socketOpen}>
        {s?.connected ? 'Disconnect' : 'Connect'}
      </button>
    </div>

    <dl class="counters">
      <div><dt>Frame</dt><dd class="num">{latest?.frame ?? '–'}</dd></div>
      <div><dt>Points</dt><dd class="num">{latest?.points.length ?? '–'}</dd></div>
      <div><dt>Rate</dt><dd class="num">{radar.fps ? radar.fps.toFixed(1) : '–'} fps</dd></div>
      <div><dt>Firmware</dt><dd class="num">{s?.deviceVersion ?? '–'}</dd></div>
    </dl>

    <label class="pause">
      <input type="checkbox" bind:checked={radar.paused} /> Pause
    </label>
  </header>

  {#if versionMismatch}
    <div class="banner" role="alert">
      ⚠ Device firmware {s?.deviceVersion} differs from the SDK ({s?.sdkVersion}); cfgs and the data format may not match.
    </div>
  {/if}
  {#if radar.error}
    <div class="banner" role="alert">
      ⚠ {radar.error}
      <button onclick={() => (radar.error = null)}>Dismiss</button>
    </div>
  {/if}

  <div class="main">
    <aside>
      <ConfigPanel />
      <RecordReplay />
      <CliConsole />
    </aside>

    <section class="plots">
      <div class="controls">
        <label>
          View
          <select bind:value={viewRange}>
            {#each [1, 2, 3, 5, 8, 12] as r (r)}<option value={r}>{r} m</option>{/each}
          </select>
        </label>
        <label>
          Color points by
          <select bind:value={colorBy}>
            <option value="velocity">velocity</option>
            <option value="snr">SNR</option>
          </select>
        </label>
        <span class="legend">
          {#if colorBy === 'velocity'}
            <span class="num">−{velMax.toFixed(1)}</span>
            <span class="bar" style:background={gradientCss('diverging', dark)}></span>
            <span class="num">+{velMax.toFixed(1)} m/s</span>
            <span class="muted">(toward · static · away)</span>
          {:else}
            <span class="num">10</span>
            <span class="bar" style:background={gradientCss('seqPoint', dark)}></span>
            <span class="num">40 dB</span>
          {/if}
        </span>
        <label>
          Trail
          <select bind:value={persist}>
            {#each [1, 3, 5, 10, 20] as n (n)}<option value={n}>{n === 1 ? 'off' : `${n} frames`}</option>{/each}
          </select>
        </label>
      </div>
      <div class="grid">
        {#each views as _, i (i)}
          <PlotPanel bind:view={views[i]} {viewRange} {colorBy} {persist} />
        {/each}
      </div>
    </section>
  </div>
</div>

<style>
  .app {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .top {
    display: flex;
    align-items: center;
    gap: 20px;
    padding: 10px 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  h1 {
    font-size: 16px;
    margin: 0;
  }
  .conn {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .pill .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--critical);
  }
  .pill.warn .dot {
    background: var(--warning);
  }
  .pill.ok .dot {
    background: var(--good);
  }
  .counters {
    display: flex;
    gap: 18px;
    margin: 0 0 0 auto;
  }
  .counters div {
    display: flex;
    flex-direction: column;
  }
  dt {
    font-size: 11px;
    color: var(--text-muted);
  }
  dd {
    margin: 0;
    font-weight: 600;
  }
  .pause {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 16px;
    background: var(--surface-2);
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  .main {
    flex: 1;
    display: flex;
    min-height: 0;
  }
  aside {
    width: 320px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 14px 16px;
    overflow-y: auto;
    border-right: 1px solid var(--border);
  }
  .plots {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    padding: 10px 12px 12px;
    gap: 10px;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 18px;
    flex-wrap: wrap;
    font-size: 13px;
    color: var(--text-secondary);
  }
  .controls label {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .legend {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
  }
  .legend .bar {
    width: 90px;
    height: 8px;
    border-radius: 2px;
  }
  .muted {
    color: var(--text-muted);
  }
  .grid {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 10px;
    min-height: 0;
  }

  @media (max-width: 900px) {
    .main {
      flex-direction: column;
    }
    aside {
      width: auto;
      border-right: none;
      border-bottom: 1px solid var(--border);
    }
    .grid {
      grid-template-columns: 1fr;
      grid-template-rows: repeat(4, 340px);
    }
  }
</style>

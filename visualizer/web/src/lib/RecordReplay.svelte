<script lang="ts">
  import { getJson, radar } from './radar.svelte'

  let logs = $state<{ name: string; bytes: number }[]>([])
  let selected = $state('')
  let periodMs = $state(100)

  const recording = $derived(radar.status?.recording)
  const replaying = $derived(radar.status?.replaying)

  async function refresh() {
    logs = await getJson('/api/logs')
    if (!logs.some((l) => l.name === selected)) selected = logs[0]?.name ?? ''
  }

  $effect(() => {
    // refresh the list when a recording finishes
    void recording
    refresh()
  })

  $effect(() => {
    const fp = radar.status?.cfgInfo?.frame_period_ms
    if (fp) periodMs = fp
  })

  function play() {
    radar.clearHistory()
    radar.send({ type: 'replay', name: selected, periodMs })
  }

  const kb = (b: number) => (b < 1024 * 1024 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`)
</script>

<section>
  <h2>Record &amp; replay</h2>
  <div class="row">
    {#if recording}
      <button onclick={() => radar.send({ type: 'record', on: false })}>
        <span class="dot" aria-hidden="true"></span> Stop recording
      </button>
      <span class="mono file" title={recording}>{recording}</span>
    {:else}
      <button onclick={() => radar.send({ type: 'record', on: true })} disabled={!radar.status?.connected}>
        Record
      </button>
      <span class="hint">raw bytes → logs/</span>
    {/if}
  </div>
  <div class="row">
    <select bind:value={selected} aria-label="Log file" onfocus={refresh}>
      {#each logs as l (l.name)}
        <option value={l.name}>{l.name} ({kb(l.bytes)})</option>
      {:else}
        <option value="">no logs yet</option>
      {/each}
    </select>
  </div>
  <div class="row">
    <label class="hint">every <input type="number" min="10" step="10" bind:value={periodMs} /> ms</label>
    {#if replaying}
      <button onclick={() => radar.send({ type: 'stopReplay' })}>Stop</button>
    {:else}
      <button onclick={play} disabled={!selected}>Replay</button>
    {/if}
  </div>
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  h2 {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
    margin: 0;
  }
  .row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .row > :last-child:is(button) {
    margin-left: auto;
  }
  select {
    width: 100%;
  }
  input[type='number'] {
    width: 70px;
  }
  .hint {
    font-size: 12px;
    color: var(--text-secondary);
  }
  .file {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--critical);
    margin-right: 4px;
  }
</style>

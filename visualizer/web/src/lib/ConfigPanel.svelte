<script lang="ts">
  import { onMount } from 'svelte'
  import { getJson, radar, type CfgInfo } from './radar.svelte'

  let cfgs = $state<{ name: string; source: string }[]>([])
  let selected = $state('')
  let uploaded = $state<{ name: string; text: string } | null>(null)
  let preview = $state<CfgInfo | null>(null)
  let previewError = $state<string | null>(null)
  let fileInput: HTMLInputElement

  const sending = $derived(radar.status?.sendingCfg ?? false)
  const active = $derived(radar.status?.activeCfg)
  // Show what's running once sent; otherwise what's selected
  const info = $derived(preview ?? radar.status?.cfgInfo ?? null)

  onMount(async () => {
    cfgs = await getJson('/api/cfgs')
    selected = cfgs.find((c) => c.name.endsWith('profile_4T4R_tdm.cfg'))?.name ?? cfgs[0]?.name ?? ''
    await loadPreview()
  })

  async function loadPreview() {
    previewError = null
    if (uploaded) {
      const r = await getJson<{ info: CfgInfo | null }>('/api/cfg-info', { method: 'POST', body: uploaded.text })
      preview = r.info
    } else if (selected) {
      preview = (await getJson<{ info: CfgInfo | null }>(`/api/cfg?name=${encodeURIComponent(selected)}`)).info
    }
    if (!preview) previewError = 'No chirp/frame settings in this cfg (e.g. a monitors-only file).'
    radar.selectedInfo = preview
  }

  async function onUpload(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (!file) return
    uploaded = { name: file.name, text: await file.text() }
    await loadPreview()
  }

  function clearUpload() {
    uploaded = null
    fileInput.value = ''
    loadPreview()
  }

  function send() {
    radar.clearHistory()
    if (uploaded) radar.send({ type: 'sendCfg', name: `upload/${uploaded.name}`, text: uploaded.text })
    else radar.send({ type: 'sendCfg', name: selected })
  }

  const rows = $derived(
    info
      ? [
          ['Max range', `${info.max_range_m.toFixed(2)} m`],
          ['Range resolution', `${(info.range_resolution_m * 100).toFixed(1)} cm`],
          ['Max velocity', `±${info.max_velocity_mps.toFixed(2)} m/s`],
          ['Velocity resolution', `${info.velocity_resolution_mps.toFixed(2)} m/s`],
          ['Start frequency', `${info.start_freq_ghz.toFixed(2)} GHz`],
          ['Bandwidth', `${info.bandwidth_ghz.toFixed(3)} GHz`],
          ['Frame period', `${info.frame_period_ms} ms`],
          ['Chirping per frame', `${(info.active_frame_time_us / 1000).toFixed(2)} ms`],
          ['Antennas', `${info.num_tx} TX × ${info.num_rx} RX`],
          ['Range × Doppler bins', `${info.num_range_bins} × ${info.num_doppler_bins}`],
          [
            'Outputs',
            [
              info.point_cloud && 'points',
              info.range_profile && 'range profile',
              info.range_doppler_heatmap && 'heatmap',
              info.stats && 'stats',
            ]
              .filter(Boolean)
              .join(', ') || 'none',
          ],
          ['Low power', info.low_power ? 'on' : 'off'],
          ['UART per frame (est.)', `${(info.uart_bytes_estimate / 1024).toFixed(1)} KB`],
        ]
      : [],
  )
</script>

<section>
  <h2>Configuration</h2>
  {#if uploaded}
    <div class="row">
      <span class="file" title={uploaded.name}>{uploaded.name}</span>
      <button onclick={clearUpload}>Clear</button>
    </div>
  {:else}
    <select bind:value={selected} onchange={loadPreview} aria-label="Preset configuration">
      {#each cfgs as c (c.name)}
        <option value={c.name}>{c.name}</option>
      {/each}
    </select>
  {/if}
  <div class="row">
    <button onclick={() => fileInput.click()}>Upload .cfg…</button>
    <input type="file" accept=".cfg,.txt" bind:this={fileInput} onchange={onUpload} hidden />
    <button class="primary" onclick={send} disabled={sending || !radar.socketOpen}>
      {sending ? 'Sending…' : 'Send to device'}
    </button>
  </div>
  {#if active}
    <p class="hint">Running: <span class="mono">{active}</span></p>
  {/if}
  {#if info?.low_power}
    <p class="hint">Low-power cfg: the CLI may stop answering while streaming. Press the EVM reset button before sending a new cfg.</p>
  {/if}

  {#if previewError}
    <p class="hint">{previewError}</p>
  {:else if info}
    {#if info.warnings.length}
      <ul class="warnings" role="alert">
        {#each info.warnings as w (w)}
          <li><span aria-hidden="true">⚠</span> {w}</li>
        {/each}
      </ul>
    {/if}
    <table>
      <tbody>
        {#each rows as [k, v] (k)}
          <tr><th>{k}</th><td class="num">{v}</td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
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
  .row .primary {
    margin-left: auto;
  }
  select {
    width: 100%;
  }
  .file {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hint {
    margin: 0;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .warnings {
    margin: 0;
    padding: 6px 8px;
    list-style: none;
    font-size: 12px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-left: 3px solid var(--warning);
    border-radius: 4px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  table {
    border-collapse: collapse;
    font-size: 12px;
  }
  th {
    text-align: left;
    font-weight: normal;
    color: var(--text-secondary);
    padding: 2px 8px 2px 0;
  }
  td {
    text-align: right;
    padding: 2px 0;
  }
  tr + tr {
    border-top: 1px solid var(--grid);
  }
</style>

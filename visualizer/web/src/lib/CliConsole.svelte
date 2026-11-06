<script lang="ts">
  import { tick } from 'svelte'
  import { radar } from './radar.svelte'

  let input = $state('')
  let list: HTMLOListElement

  function submit(e: SubmitEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text) return
    radar.send({ type: 'command', text })
    input = ''
  }

  $effect(() => {
    void radar.cli.length
    tick().then(() => list?.scrollTo({ top: list.scrollHeight }))
  })
</script>

<section>
  <h2>CLI</h2>
  <ol bind:this={list} class="mono" aria-live="polite">
    {#each radar.cli as e (e.id)}
      <li class:err={!e.ok}>
        <span class="status" aria-label={e.ok ? 'done' : 'error'}>{e.ok ? '✓' : '✗'}</span>
        <span class="cmd">{e.command}</span>
        {#if !e.ok || e.reply.some((l) => l !== 'Done')}
          {#each e.reply.filter((l) => l !== 'Done') as line, i (i)}
            <div class="reply">{line}</div>
          {/each}
        {/if}
      </li>
    {:else}
      <li class="empty">Commands and replies appear here.</li>
    {/each}
  </ol>
  <form onsubmit={submit}>
    <input type="text" bind:value={input} placeholder="version, sensorStop 0, …" aria-label="CLI command" />
    <button type="submit" disabled={!radar.socketOpen}>Send</button>
  </form>
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-height: 0;
    flex: 1;
  }
  h2 {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
    margin: 0;
  }
  ol {
    list-style: none;
    margin: 0;
    padding: 6px 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: auto;
    flex: 1;
    min-height: 120px;
  }
  li {
    padding: 1px 0;
  }
  .status {
    display: inline-block;
    width: 14px;
    color: var(--good-text);
  }
  .err .status {
    color: var(--critical);
  }
  .err .cmd {
    font-weight: 600;
  }
  .reply {
    padding-left: 14px;
    color: var(--text-secondary);
    white-space: pre-wrap;
  }
  .empty {
    color: var(--text-muted);
  }
  form {
    display: flex;
    gap: 8px;
  }
  form input {
    flex: 1;
    min-width: 0;
    font-family: var(--mono);
    font-size: 12px;
  }
</style>

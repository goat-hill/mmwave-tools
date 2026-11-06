<script lang="ts">
  import { onMount } from 'svelte'
  import { gradientCss, isDark, niceTicks, onThemeChange, seqFill, token } from './colors'
  import type { Frame } from './radar.svelte'

  interface Props {
    rd: NonNullable<Frame['rangeDoppler']>
    rangeRes: number | null
    velRes: number | null
  }

  let { rd, rangeRes, velRes }: Props = $props()

  let wrap: HTMLDivElement
  let canvas: HTMLCanvasElement
  let width = $state(0)
  let height = $state(0)
  let themeTick = $state(0)
  let hover = $state<{ r: number; c: number; left: number; top: number } | null>(null)
  // running color range (plain vars: draw() must not depend on its own output)
  let lo = 0
  let hi = 1
  let seeded = false
  let legend = $state({ lo: 0, hi: 1 })

  const PAD = { l: 44, r: 12, t: 10, b: 32 }
  const half = $derived(Math.floor(rd.cols / 2))

  /** Display column -> Doppler bin (fftshift: zero velocity in the middle). */
  const binOf = (c: number) => (c + Math.ceil(rd.cols / 2)) % rd.cols
  const velOf = (c: number) => (c - half) * (velRes ?? 1)
  const rangeOf = (r: number) => r * (rangeRes ?? 1)
  const valueAt = (r: number, c: number) => rd.data[r * rd.cols + binOf(c)]

  function box() {
    return [PAD.l, PAD.t, width - PAD.l - PAD.r, height - PAD.t - PAD.b] as const
  }

  function draw() {
    if (!canvas || !width || !height) return
    const dpr = devicePixelRatio || 1
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
    const ctx = canvas.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = token('--surface')
    ctx.fillRect(0, 0, width, height)

    // smoothed auto-range so the colors don't flicker frame to frame
    let mn = Infinity
    let mx = -Infinity
    for (const v of rd.data) {
      if (v < mn) mn = v
      if (v > mx) mx = v
    }
    if (!seeded) {
      lo = mn
      hi = mx
      seeded = true
    } else {
      lo += (mn - lo) * 0.2
      hi += (mx - hi) * 0.2
    }
    legend = { lo, hi }
    const span = Math.max(1, hi - lo)

    const dark = isDark()
    const img = new OffscreenCanvas(rd.cols, rd.rows)
    const ictx = img.getContext('2d')!
    for (let r = 0; r < rd.rows; r++) {
      for (let c = 0; c < rd.cols; c++) {
        ictx.fillStyle = seqFill((valueAt(r, c) - lo) / span, dark)
        ictx.fillRect(c, rd.rows - 1 - r, 1, 1)
      }
    }
    const [x0, y0, w, h] = box()
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(img, x0, y0, w, h)

    // axes
    ctx.font = '11px system-ui, sans-serif'
    ctx.fillStyle = token('--text-muted')
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    const vMin = velOf(0)
    const vMax = velOf(rd.cols - 1)
    for (const v of niceTicks(vMin, vMax, 6)) {
      const x = x0 + ((v - vMin) / (vMax - vMin || 1)) * w
      ctx.fillText(String(v), x, y0 + h + 4)
    }
    ctx.textBaseline = 'bottom'
    ctx.fillText(velRes ? 'velocity (m/s)' : 'Doppler bin', x0 + w / 2, height - 2)
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    const rMax = rangeOf(rd.rows)
    for (const v of niceTicks(0, rMax, 5)) ctx.fillText(String(v), x0 - 6, y0 + h - (v / rMax) * h)
    ctx.save()
    ctx.translate(12, y0 + h / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.textAlign = 'center'
    ctx.fillText(rangeRes ? 'range (m)' : 'range bin', 0, 0)
    ctx.restore()

    if (hover) {
      ctx.strokeStyle = token('--text-primary')
      ctx.lineWidth = 1.5
      ctx.strokeRect(x0 + (hover.c * w) / rd.cols, y0 + ((rd.rows - 1 - hover.r) * h) / rd.rows, w / rd.cols, h / rd.rows)
    }
  }

  function onMove(e: PointerEvent) {
    const rect = canvas.getBoundingClientRect()
    const [x0, y0, w, h] = box()
    const c = Math.floor(((e.clientX - rect.left - x0) / w) * rd.cols)
    const r = rd.rows - 1 - Math.floor(((e.clientY - rect.top - y0) / h) * rd.rows)
    hover = c >= 0 && c < rd.cols && r >= 0 && r < rd.rows
      ? { r, c, left: e.clientX - rect.left, top: e.clientY - rect.top }
      : null
  }

  onMount(() => {
    const ro = new ResizeObserver(([entry]) => {
      width = entry.contentRect.width
      height = entry.contentRect.height
    })
    ro.observe(wrap)
    const off = onThemeChange(() => themeTick++)
    return () => {
      ro.disconnect()
      off()
    }
  })

  $effect(() => {
    void [rd, width, height, themeTick, hover]
    draw()
  })
</script>

<div class="wrap" bind:this={wrap}>
  <canvas
    bind:this={canvas}
    style:width="{width}px"
    style:height="{height}px"
    onpointermove={onMove}
    onpointerleave={() => (hover = null)}
  ></canvas>
  <div class="legend">
    <span class="num">{legend.lo.toFixed(0)} dB</span>
    <span class="bar" style:background={gradientCss('seqFill', themeTick >= 0 && isDark())}></span>
    <span class="num">{legend.hi.toFixed(0)} dB</span>
  </div>
  {#if hover}
    <div class="tip" style:left="{hover.left}px" style:top="{hover.top}px">
      <div><strong class="num">{valueAt(hover.r, hover.c).toFixed(1)} dB</strong></div>
      <div class="num muted">
        {rangeRes ? `${rangeOf(hover.r).toFixed(2)} m` : `bin ${hover.r}`} ·
        {velRes ? `${velOf(hover.c).toFixed(2)} m/s` : `Doppler ${hover.c - half}`}
      </div>
    </div>
  {/if}
</div>

<style>
  .wrap {
    position: absolute;
    inset: 0;
  }
  canvas {
    display: block;
  }
  .legend {
    position: absolute;
    top: 14px;
    right: 18px;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--surface);
    padding: 2px 6px;
    border-radius: 4px;
  }
  .bar {
    width: 80px;
    height: 8px;
    border-radius: 2px;
  }
  .tip {
    position: absolute;
    transform: translate(12px, -50%);
    pointer-events: none;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 12px;
    white-space: nowrap;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  }
  .muted {
    color: var(--text-secondary);
  }
</style>

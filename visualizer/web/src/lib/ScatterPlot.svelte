<script lang="ts">
  import { onMount } from 'svelte'
  import { diverging, isDark, niceTicks, onThemeChange, seqPoint, token } from './colors'
  import type { Frame, Point } from './radar.svelte'

  interface Props {
    frames: Frame[]
    persist: number
    /** Point indices to plot: 0 = x, 1 = y, 2 = z */
    xIdx: 0 | 1 | 2
    yIdx: 0 | 1 | 2
    xDomain: [number, number]
    yDomain: [number, number]
    xLabel: string
    yLabel: string
    colorBy: 'velocity' | 'snr'
    velMax: number
    snrDomain: [number, number]
    /** Draw field-of-view rays from the sensor at ± this many degrees from +y (top view). */
    fovDeg?: number
  }

  let { frames, persist, xIdx, yIdx, xDomain, yDomain, xLabel, yLabel, colorBy, velMax, snrDomain, fovDeg }: Props =
    $props()

  let wrap: HTMLDivElement
  let canvas: HTMLCanvasElement
  let width = $state(0)
  let height = $state(0)
  let themeTick = $state(0)
  let hover = $state<{ p: Point; left: number; top: number } | null>(null)

  const PAD = { l: 44, r: 12, t: 10, b: 32 }

  /** Equal-aspect mapping from meters to CSS pixels, centered in the plot area. */
  function geometry(w: number, h: number) {
    const pw = w - PAD.l - PAD.r
    const ph = h - PAD.t - PAD.b
    const scale = Math.min(pw / (xDomain[1] - xDomain[0]), ph / (yDomain[1] - yDomain[0]))
    const ox = PAD.l + (pw - scale * (xDomain[1] - xDomain[0])) / 2
    const oy = PAD.t + (ph - scale * (yDomain[1] - yDomain[0])) / 2
    return {
      sx: (v: number) => ox + (v - xDomain[0]) * scale,
      sy: (v: number) => oy + (yDomain[1] - v) * scale,
      box: [ox, oy, scale * (xDomain[1] - xDomain[0]), scale * (yDomain[1] - yDomain[0])] as const,
    }
  }

  function pointColor(p: Point, dark: boolean) {
    if (colorBy === 'velocity') return diverging(p[3] / velMax, dark)
    return seqPoint((p[4] - snrDomain[0]) / (snrDomain[1] - snrDomain[0]), dark)
  }

  function draw() {
    if (!canvas || !width || !height) return
    const dpr = devicePixelRatio || 1
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
    const ctx = canvas.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const dark = isDark()
    const surface = token('--surface')
    const { sx, sy, box } = geometry(width, height)

    ctx.fillStyle = surface
    ctx.fillRect(0, 0, width, height)

    // grid + ticks
    ctx.lineWidth = 1
    ctx.font = '11px system-ui, sans-serif'
    ctx.fillStyle = token('--text-muted')
    ctx.strokeStyle = token('--grid')
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    for (const v of niceTicks(xDomain[0], xDomain[1], 6)) {
      const x = Math.round(sx(v)) + 0.5
      ctx.beginPath()
      ctx.moveTo(x, box[1])
      ctx.lineTo(x, box[1] + box[3])
      ctx.stroke()
      ctx.fillText(String(v), x, box[1] + box[3] + 4)
    }
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    for (const v of niceTicks(yDomain[0], yDomain[1], 5)) {
      const y = Math.round(sy(v)) + 0.5
      ctx.beginPath()
      ctx.moveTo(box[0], y)
      ctx.lineTo(box[0] + box[2], y)
      ctx.stroke()
      ctx.fillText(String(v), box[0] - 6, y)
    }
    ctx.textAlign = 'center'
    ctx.textBaseline = 'bottom'
    ctx.fillText(xLabel, box[0] + box[2] / 2, height - 2)
    ctx.save()
    ctx.translate(12, box[1] + box[3] / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.textBaseline = 'middle'
    ctx.fillText(yLabel, 0, 0)
    ctx.restore()

    ctx.save()
    ctx.beginPath()
    ctx.rect(box[0], box[1], box[2], box[3])
    ctx.clip()

    // field of view rays
    if (fovDeg) {
      ctx.strokeStyle = token('--axis')
      ctx.setLineDash([])
      const r = Math.max(xDomain[1], yDomain[1]) * 2
      for (const s of [-1, 1]) {
        const a = (s * fovDeg * Math.PI) / 180
        ctx.beginPath()
        ctx.moveTo(sx(0), sy(0))
        ctx.lineTo(sx(r * Math.sin(a)), sy(r * Math.cos(a)))
        ctx.stroke()
      }
    }

    // sensor marker
    ctx.fillStyle = token('--text-secondary')
    ctx.beginPath()
    ctx.arc(sx(0), sy(0), 4, 0, Math.PI * 2)
    ctx.fill()

    // points: oldest first so the newest frame is on top; older frames fade
    const shown = frames.slice(-Math.max(1, persist))
    shown.forEach((f, i) => {
      const age = shown.length - 1 - i
      ctx.globalAlpha = age === 0 ? 1 : 0.15 + 0.5 * (1 - age / shown.length)
      for (const p of f.points) {
        const x = sx(p[xIdx])
        const y = sy(p[yIdx])
        ctx.beginPath()
        ctx.arc(x, y, 6, 0, Math.PI * 2) // 2px surface ring around the 8px dot
        ctx.fillStyle = surface
        ctx.fill()
        ctx.beginPath()
        ctx.arc(x, y, 4, 0, Math.PI * 2)
        ctx.fillStyle = pointColor(p, dark)
        ctx.fill()
      }
    })
    ctx.globalAlpha = 1
    ctx.restore()

    if (hover) {
      ctx.strokeStyle = token('--text-primary')
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(sx(hover.p[xIdx]), sy(hover.p[yIdx]), 7, 0, Math.PI * 2)
      ctx.stroke()
    }
  }

  function onMove(e: PointerEvent) {
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const { sx, sy } = geometry(width, height)
    let best: Point | null = null
    let bestD = 24 // px hit radius
    for (const p of frames.at(-1)?.points ?? []) {
      const d = Math.hypot(sx(p[xIdx]) - mx, sy(p[yIdx]) - my)
      if (d < bestD) {
        bestD = d
        best = p
      }
    }
    hover = best ? { p: best, left: sx(best[xIdx]), top: sy(best[yIdx]) } : null
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
    // redraw whenever any of these change
    void [frames, persist, xDomain, yDomain, colorBy, velMax, snrDomain, width, height, themeTick, hover]
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
  {#if hover}
    <div class="tip" style:left="{hover.left}px" style:top="{hover.top}px">
      <div><strong class="num">{hover.p[3].toFixed(2)} m/s</strong> <span>velocity</span></div>
      <div><strong class="num">{hover.p[4].toFixed(1)} dB</strong> <span>SNR</span></div>
      <div class="num muted">x {hover.p[0].toFixed(2)} · y {hover.p[1].toFixed(2)} · z {hover.p[2].toFixed(2)} m</div>
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
  .tip span,
  .muted {
    color: var(--text-secondary);
  }
</style>

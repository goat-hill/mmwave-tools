<script lang="ts">
  import { onMount } from 'svelte'
  import uPlot from 'uplot'
  import 'uplot/dist/uPlot.min.css'
  import { onThemeChange, token } from './colors'

  interface Series {
    label: string
    /** CSS custom property holding the series color, e.g. '--series-1' */
    color: string
    unit: string
    digits?: number
  }

  interface Props {
    data: uPlot.AlignedData
    series: Series[]
    xLabel: string
    xUnit: string
    xDigits?: number
    yLabel: string
    yRange?: [number, number]
  }

  let { data, series, xLabel, xUnit, xDigits = 2, yLabel, yRange }: Props = $props()

  let wrap: HTMLDivElement
  let plot: uPlot | null = null

  const fmt = (v: number | null | undefined, d: number, unit: string) => (v == null ? '–' : `${v.toFixed(d)} ${unit}`)

  function axis(label: string): uPlot.Axis {
    return {
      label,
      stroke: token('--text-muted'),
      grid: { stroke: token('--grid'), width: 1 },
      ticks: { stroke: token('--grid'), width: 1 },
      font: '11px system-ui, sans-serif',
      labelFont: '11px system-ui, sans-serif',
    }
  }

  function create() {
    plot?.destroy()
    const rect = wrap.getBoundingClientRect()
    const opts: uPlot.Options = {
      width: Math.max(100, rect.width),
      height: Math.max(80, rect.height - 34),
      scales: { x: { time: false }, y: yRange ? { range: yRange } : { auto: true } },
      axes: [axis(xLabel), axis(yLabel)],
      cursor: { points: { size: 8 }, drag: { x: false, y: false } },
      legend: { live: true },
      series: [
        { label: xLabel, value: (_u, v) => fmt(v, xDigits, xUnit) },
        ...series.map((s) => ({
          label: s.label,
          stroke: token(s.color),
          width: 2,
          points: { show: false },
          value: (_u: uPlot, v: number | null) => fmt(v, s.digits ?? 1, s.unit),
        })),
      ],
    }
    plot = new uPlot(opts, data, wrap)
  }

  onMount(() => {
    create()
    const ro = new ResizeObserver(() => {
      const rect = wrap.getBoundingClientRect()
      plot?.setSize({ width: Math.max(100, rect.width), height: Math.max(80, rect.height - 34) })
    })
    ro.observe(wrap)
    const off = onThemeChange(create)
    return () => {
      ro.disconnect()
      off()
      plot?.destroy()
    }
  })

  $effect(() => {
    plot?.setData(data)
  })
</script>

<div class="wrap" bind:this={wrap}></div>

<style>
  .wrap {
    position: absolute;
    inset: 0;
  }
  .wrap :global(.u-legend) {
    font-size: 12px;
    color: var(--text-secondary);
    text-align: left;
    padding-left: 44px;
  }
  .wrap :global(.u-legend .u-value) {
    color: var(--text-primary);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  /* line keys, not boxes */
  .wrap :global(.u-legend .u-marker) {
    width: 14px !important;
    height: 0 !important;
    border-width: 0 0 2px 0 !important;
    background: none !important;
    vertical-align: middle;
  }
  .wrap :global(.u-axis) {
    color: var(--text-muted);
  }
</style>

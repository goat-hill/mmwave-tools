// Color scales from the dataviz reference palette, interpolated in OKLab.

type Lab = [number, number, number]

function hexToLab(hex: string): Lab {
  const n = parseInt(hex.slice(1), 16)
  const lin = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const v = c / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  const [r, g, b] = lin
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function labToCss([L, A, B]: Lab): string {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((v) => {
    const c = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055
    return Math.round(Math.min(1, Math.max(0, c)) * 255)
  })
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`
}

/** A piecewise-linear OKLab ramp; returns a 256-entry lookup table. */
function ramp(stops: string[]): string[] {
  const labs = stops.map(hexToLab)
  return Array.from({ length: 256 }, (_, i) => {
    const t = (i / 255) * (labs.length - 1)
    const k = Math.min(labs.length - 2, Math.floor(t))
    const f = t - k
    const a = labs[k]
    const b = labs[k + 1]
    return labToCss([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f])
  })
}

// Blue sequential ramp (palette.md steps 100..700)
const BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']

// Points sit on the surface, so the lightest step must stay visible:
// light mode starts at step 250, dark mode ends at step 600 (palette.md ordinal rule).
const SEQ_POINTS_LIGHT = ramp(['#86b6ef', '#3987e5', '#256abf', '#184f95', '#0d366b'])
const SEQ_POINTS_DARK = ramp(['#184f95', '#256abf', '#3987e5', '#86b6ef', '#cde2fb'])
// Heatmap cells may recede into the surface at "near zero": full ramp.
const SEQ_FILL_LIGHT = ramp(BLUE)
const SEQ_FILL_DARK = ramp([...BLUE].reverse())

// Diverging blue <-> red with a gray midpoint. The midpoint is darker than the
// palette's fill gray so zero-velocity dots stay visible on the surface.
const DIV_LIGHT = ramp(['#184f95', '#2a78d6', '#a3a29b', '#e34948', '#a8262a'])
const DIV_DARK = ramp(['#86b6ef', '#3987e5', '#77766f', '#e66767', '#f09a9a'])

export function isDark(): boolean {
  return getComputedStyle(document.documentElement).colorScheme === 'dark'
}

function lookup(table: string[], t: number): string {
  return table[Math.round(Math.min(1, Math.max(0, t)) * 255)]
}

/** Sequential color for a point, t in [0, 1]. */
export const seqPoint = (t: number, dark: boolean) => lookup(dark ? SEQ_POINTS_DARK : SEQ_POINTS_LIGHT, t)
/** Sequential color for a heatmap cell, t in [0, 1]. */
export const seqFill = (t: number, dark: boolean) => lookup(dark ? SEQ_FILL_DARK : SEQ_FILL_LIGHT, t)
/** Diverging color, t in [-1, 1]; negative = toward the sensor (blue). */
export const diverging = (t: number, dark: boolean) => lookup(dark ? DIV_DARK : DIV_LIGHT, (t + 1) / 2)

/** CSS gradient strings for legends. */
export function gradientCss(kind: 'seqPoint' | 'seqFill' | 'diverging', dark: boolean): string {
  const fn = kind === 'diverging' ? (t: number) => diverging(t * 2 - 1, dark)
    : kind === 'seqPoint' ? (t: number) => seqPoint(t, dark) : (t: number) => seqFill(t, dark)
  return `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map(fn).join(', ')})`
}

/** Current value of a CSS custom property on :root. */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** Re-run `cb` when the OS color scheme changes. Returns an unsubscribe. */
export function onThemeChange(cb: () => void): () => void {
  const mq = matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}

/** "Nice" tick values covering [min, max]. */
export function niceTicks(min: number, max: number, target = 5): number[] {
  const span = max - min
  if (!(span > 0)) return [min]
  const raw = span / target
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10))
  return out
}

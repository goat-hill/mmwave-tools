// Connection to server.py and the reactive state every component reads.

/** [x, y, z (m), velocity (m/s), snr (dB), noise (dB)] */
export type Point = [number, number, number, number, number, number]

export interface Frame {
  type: 'frame'
  source: 'live' | 'replay'
  frame: number
  version: string
  platform: string
  points: Point[]
  rangeProfile: number[] | null
  rangeDoppler: { rows: number; cols: number; data: number[] } | null
  stats: { procUs: number; uartUs: number; powerMw: (number | null)[]; tempC: number[] } | null
}

export interface CfgInfo {
  num_tx: number
  num_rx: number
  num_adc_samples: number
  adc_sample_rate_mhz: number
  num_range_bins: number
  num_doppler_bins: number
  start_freq_ghz: number
  center_freq_ghz: number
  slope_mhz_per_us: number
  bandwidth_ghz: number
  range_resolution_m: number
  max_range_m: number
  velocity_resolution_mps: number
  max_velocity_mps: number
  chirps_per_frame: number
  frame_period_ms: number
  active_frame_time_us: number
  point_cloud: boolean
  range_profile: boolean
  range_doppler_heatmap: boolean
  stats: boolean
  low_power: boolean
  uart_bytes_estimate: number
  warnings: string[]
}

export interface Status {
  type: 'status'
  connected: boolean
  cliPort: string | null
  dataPort: string | null
  recording: string | null
  replaying: string | null
  activeCfg: string | null
  cfgInfo: CfgInfo | null
  sendingCfg: boolean
  sdkVersion: string | null
  deviceVersion: string | null
}

export interface CliEntry {
  id: number
  command: string
  ok: boolean
  reply: string[]
}

const TEMP_HISTORY = 600 // samples (~60 s at 10 fps)
const FRAME_HISTORY = 20 // for point persistence

/** Drop the echoed command, the prompt and blank lines from a CLI reply. */
function cleanReply(command: string, reply: string): string[] {
  return reply
    .replace(/\r/g, '')
    .split('\n')
    .map((l) => l.replace(/mmwDemo:\/>/g, '').trim())
    .filter((l) => l && l !== command && !command.endsWith(l))
}

class Radar {
  socketOpen = $state(false)
  status = $state<Status | null>(null)
  /** Most recent frame, even while paused (counters keep running). */
  latest = $state.raw<Frame | null>(null)
  /** Recent frames for display, newest last; frozen while paused. */
  frames = $state.raw<Frame[]>([])
  paused = $state(false)
  frameCount = $state(0)
  fps = $state(0)
  cli = $state<CliEntry[]>([])
  error = $state<string | null>(null)
  /** Info for the cfg selected in the sidebar; used until a cfg has been sent. */
  selectedInfo = $state<CfgInfo | null>(null)

  /** Velocity at which point colors saturate: 3 Doppler steps. */
  get velMax(): number {
    const i = this.info
    return i ? Math.min(i.max_velocity_mps, 3 * i.velocity_resolution_mps) : 5
  }

  /** Info for scaling plots: the running cfg, else the selected one. */
  get info(): CfgInfo | null {
    return this.status?.cfgInfo ?? this.selectedInfo
  }
  /** [t (s), rx, tx, pm, dig] columns for the temperature chart */
  temps = $state.raw<number[][]>([[], [], [], [], []])
  /** [t (s), velocity of the fastest point (m/s) or null] columns for the speed chart */
  speeds = $state.raw<(number | null)[][]>([[], []])

  #ws: WebSocket | null = null
  #arrivals: number[] = []
  #cliId = 0
  #t0 = performance.now()

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws`)
    this.#ws = ws
    ws.onopen = () => (this.socketOpen = true)
    ws.onclose = () => {
      this.socketOpen = false
      setTimeout(() => this.connect(), 1000)
    }
    ws.onmessage = (ev) => this.#handle(JSON.parse(ev.data))
  }

  send(msg: object) {
    if (this.#ws?.readyState === WebSocket.OPEN) this.#ws.send(JSON.stringify(msg))
  }

  clearHistory() {
    this.frames = []
    this.temps = [[], [], [], [], []]
    this.speeds = [[], []]
    this.frameCount = 0
  }

  #handle(msg: any) {
    switch (msg.type) {
      case 'status':
        this.status = msg
        break
      case 'frame':
        this.#onFrame(msg)
        break
      case 'cli':
        this.cli = [
          ...this.cli.slice(-300),
          { id: this.#cliId++, command: msg.command, ok: msg.ok, reply: cleanReply(msg.command, msg.reply) },
        ]
        break
      case 'error':
        this.error = msg.message
        break
    }
  }

  #onFrame(f: Frame) {
    const now = performance.now()
    this.#arrivals = [...this.#arrivals.slice(-19), now]
    if (this.#arrivals.length > 1) {
      const span = (now - this.#arrivals[0]) / 1000
      this.fps = (this.#arrivals.length - 1) / span
    }
    this.frameCount++
    this.latest = f
    if (this.paused) return

    this.frames = [...this.frames.slice(-(FRAME_HISTORY - 1)), f]
    const t = (now - this.#t0) / 1000
    const fastest = f.points.length
      ? f.points.reduce((a, p) => (Math.abs(p[3]) > Math.abs(a[3]) ? p : a))[3]
      : null
    this.speeds = [
      [...this.speeds[0].slice(-(TEMP_HISTORY - 1)), t],
      [...this.speeds[1].slice(-(TEMP_HISTORY - 1)), fastest],
    ]
    if (f.stats) {
      this.temps = this.temps.map((col, i) =>
        [...col.slice(-(TEMP_HISTORY - 1)), i === 0 ? t : f.stats!.tempC[i - 1]],
      )
    }
  }
}

export const radar = new Radar()

export async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

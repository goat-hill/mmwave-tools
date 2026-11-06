#!/usr/bin/env python3
"""Derived radar parameters for an xWRL684x OOB demo .cfg file.

Mirrors the demo firmware's own math so the numbers match what the device uses:
  * CLI parsing:        examples/mmw_demo/mmwave_demo/source/mmw_cli.c
  * range/Doppler step: MmwDemo_... in source/dpc/dpc.c (rangeStep, dopplerStep)
  * limits/warnings:    docs/mmWave_Demo_Tuning_Guide.pdf (3.1.2, 3.1.6, 3.2.4) and the
                        UART time budget in MmwDemo_transmitProcessedOutputTask()

  python3 cfg_info.py path/to/profile.cfg
"""
import json
import sys
from dataclasses import asdict, dataclass, field

C = 3e8  # MMWDEMO_RFPARSER_SPEED_OF_LIGHT_IN_METERS_PER_SEC
APLL_MHZ = {False: 400.0, True: 396.0}  # by apllFreqShiftEn
MAX_CHIRPS_4RX = 1024                   # tuning guide 3.1.2
UART_US_PER_BYTE = 9                    # UART_BYTE_TRANSMIT_TIME1250000_US in mmwave_demo.c
ASSUMED_POINTS = 100                    # for the UART budget estimate
HWA_DET_MATRIX_BYTES = 2 * 0x4000       # CFAR input: 2 HWA banks (dpc.c hwaMemInpSize); else -30311
MIN_TESTED_CHIRP_US = 19.1              # 12.6 and 14.2 us chirps hung after 3 frames on the EVM


def pow2roundup(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def count_pairs(mask, num_pairs=8):
    """xWRL684x channelCfg masks enable antennas in bit pairs (mmw_cli.c)."""
    return sum(1 for i in range(num_pairs) if (mask >> (2 * i)) & 0b11)


@dataclass
class CfgInfo:
    num_tx: int
    num_rx: int
    num_adc_samples: int
    adc_sample_rate_mhz: float
    num_range_bins: int
    num_doppler_bins: int
    start_freq_ghz: float
    center_freq_ghz: float
    slope_mhz_per_us: float
    bandwidth_ghz: float
    range_resolution_m: float
    max_range_m: float
    velocity_resolution_mps: float
    max_velocity_mps: float
    chirps_per_frame: int
    frame_period_ms: float
    active_frame_time_us: float
    point_cloud: bool
    range_profile: bool
    range_doppler_heatmap: bool
    stats: bool
    low_power: bool
    uart_bytes_estimate: int = 0
    warnings: list = field(default_factory=list)


def parse_cfg_text(text):
    """{command: [args, ...]} for the last occurrence of each command."""
    cmds = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        name, *args = line.split()
        cmds[name] = args
        if name in ("cfarFovCfg", "cfarProcCfg") and args:
            cmds[f"{name}_{args[0]}"] = args
    return cmds


def cfg_info(text):
    cmds = parse_cfg_text(text)
    rx_mask, tx_mask = int(cmds["channelCfg"][0]), int(cmds["channelCfg"][1])
    dig_rate, bits_sel, _fir, num_adc, _mimo, ramp_end_us, _hpf = cmds["chirpComnCfg"]  # noqa
    idle_us, adc_start_raw, tx_start_us, slope, start_ghz = cmds["chirpTimingCfg"]
    chirps_burst, accum, burst_period_us, bursts, frame_ms, _nframes = cmds["frameCfg"]
    gui = [int(x) for x in cmds.get("guiMonitor", ["0"] * 6)]
    apll_shift = bool(int(cmds.get("apllFreqShiftEn", ["0"])[0]))

    num_tx, num_rx = count_pairs(tx_mask), count_pairs(rx_mask)
    num_adc = int(num_adc)
    ramp_end_us, idle_us = float(ramp_end_us), float(idle_us)
    slope_hz_s = float(slope) * 1e12
    chirps_burst, accum, bursts = int(chirps_burst), int(accum), int(bursts)

    fs_mhz = APLL_MHZ[apll_shift] / (2 * int(dig_rate))
    num_range_bins = pow2roundup(num_adc) // 2  # real-only sampling
    num_doppler_bins = pow2roundup(bursts * chirps_burst // num_tx)

    adc_start_s = (int(adc_start_raw) >> 10) / fs_mhz * 1e-6
    bandwidth = slope_hz_s * num_adc / (fs_mhz * 1e6)
    start_hz = float(start_ghz) * 1e9
    center_hz = start_hz + bandwidth / 2 + adc_start_s * slope_hz_s

    range_step = C * fs_mhz * 1e6 / (2 * slope_hz_s * 2 * num_range_bins)
    if bursts > 1:
        doppler_step = C / (2 * num_doppler_bins * center_hz * float(burst_period_us) * 1e-6)
    else:
        doppler_step = C / (2 * chirps_burst * center_hz * (idle_us + ramp_end_us) * 1e-6)
        if accum:
            doppler_step /= accum

    chirp_us = idle_us + ramp_end_us
    total_chirps = bursts * chirps_burst
    active_us = (total_chirps * chirp_us * max(1, accum) if bursts == 1
                 else bursts * float(burst_period_us))
    low_power = bool(int(cmds.get("lowPowerCfg", ["0"])[0]))

    # rough worst-case bytes per frame on the data UART
    uart_bytes = 40 + 8 + 24  # header + stats TLV
    if gui[0]:
        uart_bytes += 2 * 8 + ASSUMED_POINTS * (16 + 4)
    if gui[1] & 1:
        uart_bytes += 8 + 2 * num_range_bins
    if gui[4]:
        uart_bytes += 8 + 2 * num_range_bins * num_doppler_bins

    warnings = check_limits(
        num_tx=num_tx, num_rx=num_rx, num_adc=num_adc, fs_mhz=fs_mhz,
        skip=int(adc_start_raw), ramp_end_us=ramp_end_us, idle_us=idle_us,
        tx_start_us=float(tx_start_us), slope=float(slope), chirps_burst=chirps_burst,
        bursts=bursts, accum=accum, burst_period_us=float(burst_period_us),
        frame_ms=float(frame_ms), active_us=active_us, apll_shift=apll_shift,
        bits_sel=int(bits_sel), uart_bytes=uart_bytes,
        clutter_removal=bool(int(cmds.get("clutterRemoval", ["0"])[0])),
    )
    if chirp_us < MIN_TESTED_CHIRP_US:
        warnings.append(f"chirp period {chirp_us:.1f} us is below {MIN_TESTED_CHIRP_US} us; on the EVM, "
                        "12.6 and 14.2 us chirps stopped after 3 frames and needed a reset")
    if num_tx == 1 and int(_mimo) != 0:
        warnings.append("1 TX with MIMO pattern 1 was accepted but produced no frames on the EVM; use 0")
    det_bytes = num_range_bins * num_doppler_bins * 2
    if det_bytes > HWA_DET_MATRIX_BYTES:
        warnings.append(f"detection matrix {num_range_bins} range x {num_doppler_bins} Doppler bins = "
                        f"{det_bytes // 1024} KB exceeds the {HWA_DET_MATRIX_BYTES // 1024} KB HWA input "
                        "memory; sensorStart fails with CFAR error -30311")
    fov = cmds.get("cfarFovCfg_1")
    if fov and max(abs(float(fov[1])), abs(float(fov[2]))) < 0.95 * doppler_step * num_doppler_bins / 2:
        warnings.append(f"Doppler window cfarFovCfg 1 {fov[1]} {fov[2]} m/s is narrower than the max "
                        f"velocity ±{doppler_step * num_doppler_bins / 2:.1f} m/s; faster detections are dropped")
    if "antGeometryBoard" in cmds and not low_power:
        warnings.append("antGeometryBoard only works once per boot (firmware strtok bug); a second cfg "
                        "without a reset fails with 'Invalid antGeometryTX string'. Use antGeometryTX/RX/"
                        "Dist + compRangeBiasAndRxChanPhase instead (see cfgs/person.cfg)")

    return CfgInfo(
        num_tx=num_tx,
        num_rx=num_rx,
        num_adc_samples=num_adc,
        adc_sample_rate_mhz=fs_mhz,
        num_range_bins=num_range_bins,
        num_doppler_bins=num_doppler_bins,
        start_freq_ghz=float(start_ghz),
        center_freq_ghz=center_hz / 1e9,
        slope_mhz_per_us=float(slope),
        bandwidth_ghz=bandwidth / 1e9,
        range_resolution_m=range_step,
        max_range_m=range_step * num_range_bins,
        velocity_resolution_mps=doppler_step,
        max_velocity_mps=doppler_step * num_doppler_bins / 2,
        chirps_per_frame=bursts * chirps_burst,
        frame_period_ms=float(frame_ms),
        active_frame_time_us=active_us,
        point_cloud=bool(gui[0]),
        range_profile=bool(gui[1] & 1),
        range_doppler_heatmap=bool(gui[4]),
        stats=bool(gui[5]),
        low_power=low_power,
        uart_bytes_estimate=uart_bytes,
        warnings=warnings,
    )


def check_limits(*, num_tx, num_rx, num_adc, fs_mhz, skip, ramp_end_us, idle_us, tx_start_us,
                 slope, chirps_burst, bursts, accum, burst_period_us, frame_ms, active_us,
                 apll_shift, bits_sel, uart_bytes, clutter_removal):
    """Human-readable problems with a cfg, per TI's documented limits."""
    w = []
    total = chirps_burst * bursts
    if num_rx == 4 and total > MAX_CHIRPS_4RX:
        w.append(f"{total} chirps per frame exceeds the demo's {MAX_CHIRPS_4RX} limit with 4 RX")
    if num_tx and total % num_tx:
        w.append(f"total chirps ({total}) must be a multiple of the TX count ({num_tx})")
    per_tx = total // max(1, num_tx)
    if clutter_removal and per_tx & (per_tx - 1):
        w.append(f"clutter removal needs a power-of-2 number of chirps per TX (have {per_tx})")
    if accum >= 2 and bits_sel != 0:
        w.append("chirp accumulation: TI recommends digOutputBitsSel = 0 to avoid saturation")

    # chirp timing (tuning guide 3.1.6); the skip-sample count is the raw chirpAdcStartTime
    min_ramp = (skip + num_adc - 3) / fs_mhz
    if ramp_end_us < min_ramp:
        w.append(f"ramp end time {ramp_end_us} us < minimum {min_ramp:.2f} us")
    min_idle = max(4.1 - tx_start_us, 3.1, 1.21 + slope / 1400 * ramp_end_us,
                   (skip + num_adc + 4) / fs_mhz - ramp_end_us)
    if idle_us < min_idle:
        w.append(f"chirp idle time {idle_us} us < minimum {min_idle:.2f} us")

    burst_idle_min = 136 if apll_shift else 135
    if bursts == 1:
        need = active_us + burst_idle_min
        if burst_period_us < need:
            w.append(f"burst period {burst_period_us:.0f} us < chirping time + {burst_idle_min} us "
                     f"= {need:.0f} us")
    frame_us = frame_ms * 1000
    if frame_us < bursts * burst_period_us + 54:
        w.append(f"frame period {frame_ms} ms is shorter than the bursts + 54 us frame idle")

    uart_us = uart_bytes * UART_US_PER_BYTE
    spare_us = frame_us - bursts * burst_period_us
    if uart_us > spare_us:
        w.append(f"~{uart_bytes / 1024:.1f} KB per frame needs ~{uart_us / 1000:.0f} ms on the "
                 f"1.25 Mbaud UART but only ~{spare_us / 1000:.0f} ms is left in the frame; "
                 "the demo drops frames that don't fit")
    elif uart_us > 0.7 * spare_us:
        w.append(f"UART output (~{uart_us / 1000:.0f} ms) uses most of the frame's idle time "
                 "(processing time is not included in this estimate)")
    return w


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print(json.dumps(asdict(cfg_info(f.read())), indent=2))

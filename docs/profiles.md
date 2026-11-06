# Radar profiles

Configurations (`.cfg`) for the xWRL684x OOB demo, SDK 06.01.03.04, on the IWRL6844EVM.
The SDK profiles live in `$MMWAVE_SDK/examples/mmw_demo/mmwave_demo/profiles/`; ours are in
`cfgs/` (listed in the visualizer as `local/…`). Each local cfg starts with a comment block
saying what it changes and why.

Numbers below come from `visualizer/cfg_info.py`, which mirrors the firmware's own math
(`mmw_cli.c`, `dpc/dpc.c`). Regenerate after editing a cfg:

```sh
python3 visualizer/cfg_info.py cfgs/person.cfg
```

## Summary

| Profile | Use | Status on the EVM |
|---|---|---|
| `person.cfg` | General person detection (moving and still), performance over power | **Verified streaming**: 10.0 fps, processing 2.3–5.0 ms, ~12–15 points/frame. Detection quality not yet evaluated |
| `golf.cfg` | Golf stage 1: club/ball speed | **Verified streaming**: 19.8 fps, processing 2–3 ms. Not yet tried with a swing. Has 1-TX velocity spurs (below) |
| `profile_4T4R_tdm.cfg` (SDK) | TI default: low-power people sensing | **Verified**: 9.3–9.4 fps; detected a hand at 0.3 m; a seated person at 0.75 m was visible in the range profile but below the detection threshold |
| `profile_4T4R_tdm_sensitive.cfg` | SDK default with CFAR 9 → 6 dB and the heatmap on | Older version (with `antGeometryBoard`) ran: occasional points on a seated person. Current version untested |
| `profile_4T4R_tdm_heatmap.cfg` | SDK default with the heatmap on | Untested |
| `profile_3T4R_tdm.cfg`, `profile_2T4R_bpm.cfg` (SDK) | TI's 3-TX TDM and 2-TX BPM variants | Untested |

Low-power cfgs (`lowPowerCfg 1`) need the EVM reset button before a new cfg can be sent.
`person.cfg` and `golf.cfg` have low power off, so you can switch between them freely.

## Derived parameters

| Profile | TX×RX | ADC | Chirp µs | Chirps | Frame ms | Range × Doppler bins | Range res | Max range | Vel res | Max vel | Chirping/frame | UART est. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `profile_4T4R_tdm.cfg` (SDK) | 4×4 | 256 | 19.1 | 64 | 100 | 128 × 16 | 9.2 cm | 11.7 m | 2.09 m/s | ±16.7 m/s | 1.2 ms | 2.3 KB |
| `profile_3T4R_tdm.cfg` (SDK) | 3×4 | 256 | 19.1 | 48 | 100 | 128 × 16 | 9.2 cm | 11.7 m | 2.78 m/s | ±22.3 m/s | 0.9 ms | 2.3 KB |
| `profile_2T4R_bpm.cfg` (SDK) | 2×4 | 256 | 19.1 | 64 | 100 | 128 × 32 | 9.2 cm | 11.7 m | 2.09 m/s | ±33.4 m/s | 1.2 ms | 2.3 KB |
| `person.cfg` | 4×4 | 256 | 43.1 | 256 | 100 | 128 × 64 | 9.2 cm | 11.7 m | 0.23 m/s | ±7.4 m/s | 11.0 ms | 2.3 KB |
| `golf.cfg` | 1×4 | 128 | 19.1 | 256 | 50 | 64 × 256 | 18.3 cm | 11.7 m | 0.53 m/s | ±67.2 m/s | 4.9 ms | 2.2 KB |
| `profile_4T4R_tdm_sensitive.cfg` | 4×4 | 256 | 19.1 | 64 | 100 | 128 × 16 | 9.2 cm | 11.7 m | 2.09 m/s | ±16.7 m/s | 1.2 ms | 6.3 KB |
| `profile_4T4R_tdm_heatmap.cfg` | 4×4 | 256 | 19.1 | 64 | 100 | 128 × 16 | 9.2 cm | 11.7 m | 2.09 m/s | ±16.7 m/s | 1.2 ms | 6.3 KB |

The detection threshold (`cfarProcCfg … 9.0/6.0 …`) and the range window (`cfarFovCfg 0`,
0.25–9 m in all of these) limit what is reported, independent of the numbers above.
"UART est." assumes 100 points per frame.

## Key commands side by side

All profiles also set `adcDataDitherCfg 1`, `gpAdcMeasConfig 0 0`, `aoaProcCfg 64 64`,
`aoaFovCfg -60 60 -60 60`, `runtimeCalibCfg 1`, `adcDataSource 0 …`, `adcLogging 0`.
SDK profiles use `antGeometryBoard xWRL6844EVM`; local ones give the same geometry with
explicit commands (see [learnings](learnings.md#firmware-quirks-and-limits)).

| Command | 4T4R (SDK) | 3T4R (SDK) | 2T4R BPM (SDK) | person | golf | sensitive | heatmap |
|---|---|---|---|---|---|---|---|
| `channelCfg` | `153 255 0` | `153 63 0` | `153 15 0` | `153 255 0` | `153 3 0` | `153 255 0` | `153 255 0` |
| `chirpComnCfg` | `8 0 0 256 1 13.1 3` | `8 0 0 256 1 13.1 3` | `8 0 0 256 4 13.1 3` | `8 0 0 256 1 13.1 3` | `8 0 0 128 0 13.1 3` | `8 0 0 256 1 13.1 3` | `8 0 0 256 1 13.1 3` |
| `chirpTimingCfg` | `6 63 0 160 58` | `6 63 0 160 58` | `6 63 0 160 58` | `30 63 0 160 58` | `6 63 0 160 58` | `6 63 0 160 58` | `6 63 0 160 58` |
| `frameCfg` | `64 0 1358 1 100 0` | `48 0 1358 1 100 0` | `64 0 1358 1 100 0` | `256 0 11200 1 100 0` | `256 0 5090 1 50 0` | `64 0 1358 1 100 0` | `64 0 1358 1 100 0` |
| `guiMonitor` | `1 1 0 0 0 1` | `1 1 0 0 0 1` | `1 1 0 0 0 1` | `1 1 0 0 0 1` | `1 1 0 0 0 1` | `1 1 0 0 1 1` | `1 1 0 0 1 1` |
| `cfarProcCfg 0` | `… 9.0 0` | `… 6.0 0` | `… 9.0 0` | `… 6.0 0` | `… 9.0 0` | `… 6.0 0` | `… 9.0 0` |
| `cfarProcCfg 1` | `… 9.0 0` | `… 6.0 0` | `… 9.0 0` | `… 6.0 0` | `… 9.0 0` | `… 6.0 0` | `… 9.0 0` |
| `cfarFovCfg 1` (m/s) | `-20.16 20.16` | `-20.16 20.16` | `-20.16 20.16` | `-20.16 20.16` | `-101 101` | `-20.16 20.16` | `-20.16 20.16` |
| `clutterRemoval` | `0` | `0` | `0` | `0` | `1` | `0` | `0` |
| `factoryCalibCfg` (rxGain, TX backoff) | `44 2` | `44 2` | `44 2` | `44 0` | `44 0` | `44 2` | `44 2` |
| `lowPowerCfg` | `1` | `1` | `1` | `0` | `0` | `1` | `1` |

## person.cfg

Goal: detect people whether they move or not, with power a secondary concern (still on
USB power).

| Change from the SDK 4T4R profile | Why |
|---|---|
| `lowPowerCfg 0` | No deep sleep between frames; the CLI keeps answering, so cfgs can be changed without the reset button |
| Chirp idle 6 → 30 µs (chirp 43.1 µs), 64 → 256 chirps, burst period 11200 µs | Velocity resolution 2.09 → 0.23 m/s, so slow-moving people separate from furniture; ~+6 dB from integrating 4× more chirps |
| CFAR thresholds 9 → 6 dB | A seated person at 0.75 m stood only ~6–9 dB above neighboring range bins |
| TX backoff 2 → 0 dB | +2 dB transmit power |
| Clutter removal stays off | A still person is a person; removing the zero-velocity bin would remove them |
| Heatmap stays off | 128 × 64 bins = 16 KB per frame, which won't fit the 1.25 Mbaud UART in 100 ms |

Expect more static points (furniture, walls) than the SDK profile. Telling a still person
from a chair needs host-side processing: an empty-room background plus tracking (planned).

## golf.cfg

Goal: measure club-head and ball speed. Requirements and feasibility are discussed in
[learnings](learnings.md#golf-feasibility).

| Change from person.cfg | Why |
|---|---|
| 1 TX (`channelCfg 153 3 0`), MIMO pattern 0 | Every chirp comes from the same TX, so max velocity is set by one chirp period instead of four |
| 128 ADC samples | Keeps range × Doppler bins within the 16384-cell CFAR memory limit (64 × 256) |
| Chirp 19.1 µs (TI's timing) | Shorter chirps (12.6, 14.2 µs) hung the firmware after 3 frames |
| 256 chirps every 50 ms | 0.53 m/s resolution; 4.9 ms of chirping per 20 Hz frame |
| `cfarFovCfg 1 -101 101` | The SDK's ±20.16 m/s velocity window would drop every club and ball |
| Clutter removal on, CFAR back to 9 dB | Golf only needs moving targets; with 6 dB and no clutter removal there were ~70 noise points/frame |

Limits and known issues:

- **±67 m/s unambiguous.** Club heads (35–55 m/s) fit; ball speeds above 67 m/s wrap to
  negative velocities. Since the ball moves away from the radar, the wrap can be undone
  on the host.
- **1-TX spurs:** strong static reflectors (here at ~1.8 m and ~6.5 m) leak into velocity
  bins 0 ±1, ±64 and ±128 (≈ 0, ±33.6, ±67 m/s), ~20 false points per frame even with
  clutter removal. ±33.6 m/s is inside the club-speed range, so this needs a host filter
  (drop spur-bin points at known static ranges) or calibration from raw ADC data.
- Angle estimates are coarse with 1 TX (4 virtual antennas instead of 16).

## Adding a profile

1. Copy the closest local cfg (not an SDK one: local cfgs already avoid the
   `antGeometryBoard` once-per-boot bug) and edit it. Add a comment block at the top.
2. Run `python3 visualizer/cfg_info.py cfgs/new.cfg` and fix every warning. The checks
   cover TI's documented limits plus the ones found on the EVM (see
   [learnings](learnings.md#firmware-quirks-and-limits)).
3. Send it from the visualizer and check the CLI box for all ✓, then the frame rate and
   the processing time (Temperatures panel header).
4. Record the result in the status table above.

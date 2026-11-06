# Learnings: IWRL6844EVM + mmWave L SDK 06.01.03.04 on Linux

What we found bringing up the EVM on Ubuntu 26.04 without TI's Windows tools, what the
OOB demo firmware does and doesn't allow, and what that means for person detection and
golf. Profile details are in [profiles.md](profiles.md).

## Setup on Linux

- **TI's flasher and visualizer are Windows-only**, and `tools/visualizer/` is empty in
  the Linux SDK install. The flasher (`arprog_cmdline_6844.exe`) is a PyInstaller bundle
  of Python 3.12 bytecode with no source. Its code is plain pyserial; the Windows-only
  parts (`xds110reset.exe` for `-x`, FTDI d2xx) aren't used by a normal flash.
  `flash/extract_arprog.py` pulls the bytecode out and `flash/run_arprog.py` runs it under
  a Python 3.12 venv. It must be 3.12: compiled bytecode only runs on its own version.
- **ModemManager broke the first flash.** It probes new `ttyACM` ports with modem
  commands, and the bootloader never ACKed. `sudo systemctl stop ModemManager` fixed it.
  Stopping it has no effect on a machine without a cellular modem.
- **Ports:** with only the XDS110 USB connected, `/dev/ttyACM0` (interface 0, Application/
  User UART, UARTB) is the flash and CLI port at 115200, and `/dev/ttyACM1` (interface 3,
  Auxiliary Data Port, UARTA) carries demo data at 1,250,000 baud. The FTDI port is for
  DCA1000 / SPI capture and not needed otherwise. The XDS110 shows up in `lsusb` as
  `0451:bef3` "CC1352R1 Launchpad", a generic name for that USB ID.
- **XDS110 firmware was already 03.00.00.37**, the UARTA-capable version the SDK ships,
  so the SDK's firmware-update step wasn't needed.
- **Switches:** flashing mode is SOP0 = OFF, SOP1 = OFF in both the SDK docs and the EVM
  docs. For functional mode the SDK's generic table (SOP0 OFF, SOP1 ON) disagrees with the
  EVM docs (SOP0_H, SOP1_L); trust the EVM docs. S1.4 = S1.5 = ON routes UARTA to the
  XDS110. Power off before changing SOP; the pins are only read at boot.
- **USB power is enough** to flash and run every verified profile. The demo's power-rail
  readings are `0xFFFF` (3 rails) and 0 (1 rail) on USB, i.e. not measured, so actual
  draw is unknown. No brown-out symptoms (spontaneous resets, port drops) so far.
- **LEDs:** VSYS, PGOOD and RESET lit means powered. User LED 2 toggles every wake from
  deep sleep, so it blinks once per frame with `lowPowerCfg 1` and stops otherwise.
- **pyserial 3.5 can't open 1,250,000 baud on glibc ≥ 2.42** (`termios.error: Invalid
  argument`): it passes `BOTHER` to `tcsetattr()`. `oob_protocol.open_port()` opens at
  115200, then sets the real rate with the `TCSETS2` ioctl.

## Concepts that mattered

- **Firmware vs configuration.** The `.appimage` is flashed once. The `.cfg` is CLI text
  sent after every boot and not stored on the device: replugging USB power-cycles the
  board, which then sits idle at `mmwDemo:/>` until it gets a cfg.
- **TDM-MIMO.** With 4 TX taking turns, the 4 RX see 16 virtual antennas (good angles),
  but each TX repeats only every 4th chirp, which cuts max velocity by 4. BPM transmits
  on several TX at once with phase codes and decodes afterwards.
- **Velocity resolution** = λ / (2 × chirps per TX × chirp spacing per TX). The SDK
  profiles chirp for only 1.2 ms per 100 ms frame, so their resolution is 2.09 m/s and
  slow people land in the same "static" bin as furniture. Captured hand-wave velocities
  were exact multiples of 2.086 m/s, matching the math.
- **CFAR** declares a point when a cell is a set number of dB (`cfarProcCfg … 9.0`)
  above the average of its neighbors, in range and then in Doppler. A strong but
  "ordinary" reflector next to other strong ones doesn't pass.
- **Clutter removal** zeroes the zero-velocity bin. Great for moving targets (golf), wrong
  for "a still person is a person".
- **`guiMonitor`** chooses the streamed outputs: points, range profile, heatmap, stats.
  The range profile is the zero-velocity column of the detection matrix.
- **UART budget.** Everything per frame must leave at 1.25 Mbaud (~9 µs/byte in the
  firmware's own estimate) before the next frame, or the demo drops the frame silently.
  A 128 × 64 heatmap (16 KB, ~150 ms) doesn't fit a 100 ms frame.

## Firmware quirks and limits

Found on the device and confirmed in the demo source
(`$MMWAVE_SDK/examples/mmw_demo/mmwave_demo/source/`). `cfg_info.py` warns about the
cfg-detectable ones before sending.

| Symptom | Cause | Workaround |
|---|---|---|
| With `lowPowerCfg 1` and the sensor running, `sensorStop 0` times out | Documented: sensorStop isn't supported in low-power mode (tuning guide §3) | Reset the EVM before each new cfg, or use `lowPowerCfg 0` |
| Second cfg in a boot fails: `antGeometryBoard … Invalid antGeometryTX string` | `CLI_MmwDemo_AntGeometryBoard` `strtok()`s its built-in strings in place, so they only parse once | Explicit `antGeometryTX/RX/Dist` + `compRangeBiasAndRxChanPhase` with the same values (in all local cfgs) |
| `antGeometryTX 2 2 2 0 0 0 0 2` → `Invalid usage` | argc check (17 or 3) was written for the 8×8 xWRL688x; on 4×4 it then reads only 8 values | Pad with 8 zeros |
| `sensorStart` → `CFAR DPU config return error:-30311`, then the CLI hangs | `DPU_CFARPROCHWA_ENOMEM__DET_MATRIX_EXCEEDS_HWA_INP_MEM`: range × Doppler × 2 bytes must fit 2 × 16 KB HWA banks (`dpc.c` `hwaMemInpSize`) | Range bins × Doppler bins ≤ 16384 |
| 3 frames, then the firmware stops answering entirely | Chirp period below TI's 19.1 µs (12.6 and 14.2 µs tested); root cause not found. Likely a per-chirp processing deadline (the R5 runs at 40 MHz while chirping) | Keep chirps ≥ 19.1 µs |
| 1 TX with MIMO pattern 1 (TDM): accepted, no frames | Unknown | Use pattern 0 with 1 TX |
| 1 TX: static reflectors appear at velocity bins 0 ±1, ±N/4, ±N/2 | Consistent with a 4-chirp periodic modulation (the TX sequencer's 4-TX rotation) that MIMO decoding normally hides | Host-side filtering, or calibrate from raw ADC data |
| Commands lose characters (`apllFreqShiftEn` arrives as `pllFreqShiftEn`), or arrive empty while the sensor runs | The CLI polls its UART; bytes sent before its prompt, or while it's busy, are dropped | `send_command()` waits for the prompt, paces characters 0.5 ms apart, and resends only when the echo shows the line arrived mangled |
| A failed `sensorStart` or a hang leaves the CLI silent | Firmware assert (e.g. the frame-start check that the previous frame finished, `interrupts.c`) | Reset button or replug |
| `cfarFovCfg 1 -20.16 20.16` hides fast targets | It's a velocity window in m/s; detections outside are dropped | Widen it (golf: ±101) |
| SNR/noise ~10× too large | Header says 0.1 dB, but the value is scaled by 10 twice (`CFARDSP_CONV_PEAK_TO_LOG` already includes ×10, then `dpc.c` ×10) | Parse as 0.01 dB |
| `version` says "MMWAVE DEMO for xwrL688x" | Hardcoded string (`mmw_cli.c:505`) | Ignore; the `Platform` line is right |

TI's documented chirp-timing minimums (tuning guide §3.1.6) were necessary but not
sufficient: chirps that satisfied every formula still hung the demo.

## Device test log (2026-11-05)

Run through the visualizer backend, which sends cfgs exactly like the UI. "Hang" means
frames stopped and the CLI stopped answering until reset.

| Test | Change | Result |
|---|---|---|
| SDK `profile_4T4R_tdm.cfg` | — | ✓ 9.3–9.4 fps, 0 resyncs; hand at 0.27–0.45 m detected (123 points / 150 frames) |
| Same, seated person at 0.75 m | — | 0 points in 56 frames; range profile peak at 0.73–0.82 m, ~6–9 dB above neighbors |
| `person.cfg` → `golf.cfg` (1024 chirps, 12.6 µs) | — | `antGeometryBoard` once-per-boot failure |
| `golf.cfg` with explicit geometry | 8 geometry values | `Invalid usage` (argc wants 16) |
| `golf.cfg` (64 × 1024 bins) | padded geometry | All commands ✓, `sensorStart` error -30311, hang |
| `person.cfg` | — | ✓ 10.0 fps, processing 2.3–5.0 ms |
| `golf_256` (64 × 256, 12.6 µs) | — | 1 frame, hang |
| A: 4 TX, 12.6 µs chirps | isolate chirp speed | 3 frames, hang |
| A2: 4 TX, 14.2 µs, more ramp margin | ramp 8.2 µs, idle 6 µs | 3 frames, hang |
| A3: 4 TX, 19.1 µs, 128 ADC samples | TI timing, 64 range bins | ✓ 9.8 fps |
| B: 1 TX, 43.1 µs | isolate 1 TX | ✓ 10.0 fps |
| G19: 1 TX, 19.1 µs, 256 chirps, 50 ms | golf candidate | ✓ 19.8 fps, ~69 points/frame (mostly spurs) |
| G19b: + clutter removal, CFAR 9 dB | now `golf.cfg` | ✓ 19.8 fps, ~21 points/frame, spurs at fixed velocity bins |
| G19c: + MIMO pattern 1 | — | All ✓, no frames, hang |

Switching between low-power-off cfgs (`person` → A, A3 → B → G19 → G19b) worked without
resets once the CLI sending was paced.

## Person detection

- The SDK profile sees a seated person (clear range-profile peak) but rarely reports
  points: the peak is just under the 9 dB CFAR threshold, the person is static (same bin
  as furniture at 2.09 m/s resolution), and the board's strong close-in reflections
  (~100 dB at 0–0.2 m) raise the neighbor average.
- Lowering CFAR to 6 dB gave occasional points. `person.cfg` adds 4× the chirps and 9×
  finer velocity resolution; how well it detects people hasn't been evaluated yet.
- Telling a still person apart from a chair can't be done from one static frame. Plan:
  learn the empty room's static points, flag new static reflectors, and track people so
  a track started by motion survives sitting still (TI's people-counting approach).
- Board placement matters: upright, about chest height, facing the room, nothing close
  in front. Pointing it at the ceiling only sees people at the edge of its ±60° view.

## Golf feasibility

| Need | Typical | Implication |
|---|---|---|
| Ball speed | 55–80 m/s | Unambiguous only if one TX's chirps repeat every ≤ ~16 µs at 60 GHz |
| Club speed | 35–55 m/s | Within `golf.cfg`'s ±67 m/s |
| Time in view | ~40 ms over ~3 m | A 4.9 ms chirp window every 50 ms overlaps most shots |
| Spin | 2,000–10,000 rpm | Tens of ms of clean continuous raw data on a small, weak reflector; uncertain on this hardware. Many products measure spin with cameras |

What the hardware allowed: 1 TX at TI's 19.1 µs chirp gives ±67 m/s. Shorter chirps hang
the demo, and range × Doppler is capped at 16384 cells. Faster balls wrap and must be
unwrapped on the host. Beyond the OOB demo:

- **Raw ADC over SPI** through the EVM's own FTDI chip (`adcLogging 2`): needs a firmware
  rebuild with `ADC_DATA_LOGGING_VIA_SPI=1` and a bigger buffer, plus a Linux replacement
  for TI's Windows `adcDataSPIFTDI.exe`. One frame per frame period: characterization, not
  continuous capture.
- **Raw ADC over LVDS** with a DCA1000EVM capture board: continuous, the standard research
  setup. Its CLI can be built for Linux.
- **Custom firmware** for the product: triggered high-rate chirping and on-chip
  processing.

## Open questions and next steps

- Confirm the functional-mode SOP setting used on this board.
- Evaluate `person.cfg` with people sitting, standing and walking; then build the
  background + tracking layer.
- Golf: try `golf.cfg` with practice swings and tossed balls; build the spur filter; find
  the shortest chirp period that works between 14.2 and 19.1 µs (each failure costs a
  reset).
- Test the range-Doppler heatmap on the device (no verified profile has it on yet).
- A software reset through the XDS110 (CMSIS-DAP) would remove the reset-button step
  after hangs.
- Measure power draw (external supply, or a USB power meter), since the on-board monitors
  don't report on USB power.

#!/usr/bin/env python3
"""Configure the OOB demo and print a one-line summary per received frame.

  ../.venv/bin/python stream_check.py                     # send default cfg, stream
  ../.venv/bin/python stream_check.py --no-cfg            # just listen on the data port
  ../.venv/bin/python stream_check.py --log run1.bin      # also save raw bytes
  ../.venv/bin/python stream_check.py --replay run1.bin   # parse a saved log, no board

Default cfg: $MMWAVE_SDK/examples/mmw_demo/mmwave_demo/profiles/profile_4T4R_tdm.cfg
Close minicom first: only one program can hold the CLI port.
"""
import argparse
import os
import sys
import time

import oob_protocol as oob

DEFAULT_CFG = "examples/mmw_demo/mmwave_demo/profiles/profile_4T4R_tdm.cfg"


def default_cfg_path():
    sdk = os.environ.get("MMWAVE_SDK")
    return os.path.join(sdk, DEFAULT_CFG) if sdk else None


def print_reply(command, ok, reply):
    status = "ok " if ok else "ERR"
    print(f"  [{status}] {command}")
    if not ok:
        # show the device's full reply on failure, minus the echoed command
        for line in reply.replace("\r", "").split("\n"):
            line = line.strip()
            if line and line != command and not line.endswith(command):
                print(f"         {line}")


def summarize(frame):
    parts = [f"frame {frame.frame_number:6d}", f"pts {len(frame.points):3d}"]
    if frame.range_profile:
        rp = frame.range_profile
        peak = max(range(len(rp)), key=rp.__getitem__)
        parts.append(f"rp {len(rp)} bins peak@{peak}")
    if frame.range_doppler:
        parts.append(f"rd {len(frame.range_doppler)}")
    if frame.stats:
        s = frame.stats
        parts.append("T " + "/".join(str(t) for t in s.temp_c) + "C")
        parts.append("P " + "/".join("n/a" if p is None else f"{p:.1f}" for p in s.power_mw) + "mW")
        parts.append(f"proc {s.inter_frame_processing_us}us")
    if frame.unknown_tlvs:
        parts.append(f"other TLVs {sorted(frame.unknown_tlvs)}")
    line = "  ".join(parts)
    for (x, y, z, v), (snr, _noise) in list(zip(frame.points, frame.side_info))[:3]:
        line += f"\n      x={x:+.2f} y={y:+.2f} z={z:+.2f} m  v={v:+.2f} m/s  snr={snr:.1f} dB"
    return line


def stream(source, parser, args, log):
    """Read from a serial port or file object until Ctrl+C / EOF / --frames reached."""
    count = 0
    t0 = time.monotonic()
    first = True
    try:
        while args.frames == 0 or count < args.frames:
            data = source.read(4096)
            if not data:
                if args.replay:
                    break
                continue
            if log:
                log.write(data)
            for frame in parser.feed(data):
                if first:
                    first = False
                    print(f"first frame: SDK {frame.version_str}, platform 0x{frame.platform:X}")
                    if frame.platform != oob.PLATFORM_XWRL6844:
                        print("  warning: unexpected platform id")
                count += 1
                if not args.quiet:
                    print(summarize(frame))
    except KeyboardInterrupt:
        pass
    dt = time.monotonic() - t0
    rate = f", {count / dt:.1f} fps" if count and not args.replay else ""
    print(f"\n{count} frames{rate}, resyncs {parser.resyncs}, bad packets {parser.bad_packets}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", default="/dev/ttyACM0", help="CLI port (UARTB, 115200)")
    ap.add_argument("--data", default="/dev/ttyACM1", help="data port (UARTA)")
    ap.add_argument("--data-baud", type=int, default=1250000)
    ap.add_argument("--cfg", default=default_cfg_path(), help="cfg file to send")
    ap.add_argument("--no-cfg", action="store_true", help="don't configure, just listen")
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (0 = forever)")
    ap.add_argument("--log", help="write raw data-port bytes to this file")
    ap.add_argument("--replay", help="parse a raw log file instead of the serial port")
    ap.add_argument("--quiet", action="store_true", help="only print the final summary")
    args = ap.parse_args()

    parser = oob.FrameParser()
    log = open(args.log, "wb") if args.log else None
    try:
        if args.replay:
            with open(args.replay, "rb") as f:
                stream(f, parser, args, log)
            return

        # Open the data port before configuring so the first frames aren't missed
        with oob.open_port(args.data, args.data_baud) as data:
            data.reset_input_buffer()
            if not args.no_cfg:
                if not args.cfg:
                    sys.exit("error: no cfg; pass --cfg or set MMWAVE_SDK")
                print(f"sending {args.cfg}")
                if not oob.send_cfg(args.cli, oob.read_cfg_lines(args.cfg), on_reply=print_reply):
                    sys.exit("configuration failed")
            print(f"listening on {args.data} @ {args.data_baud} (Ctrl+C to stop)")
            stream(data, parser, args, log)
    finally:
        if log:
            log.close()


if __name__ == "__main__":
    main()

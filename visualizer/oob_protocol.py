"""Host-side protocol for the xWRL684x mmWave OOB demo (SDK 06.01.03.04).

Two parts:
  * send_cfg(): push a .cfg file to the CLI UART, one command per line
  * FrameParser: turn the raw data-UART byte stream into Frame objects

Wire format, from MmwDemo_transmitProcessedOutputTask() in
examples/mmw_demo/mmwave_demo/source/mmwave_demo.c (all little-endian):

  header (40 B): uint16 magic[4] = 0x0102 0x0304 0x0506 0x0708,
                 uint32 version, totalPacketLen, platform, frameNumber,
                 timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
  then numTLVs x { uint32 type, uint32 length (payload only), payload },
  then zero padding so totalPacketLen is a multiple of 32.
"""
import re
import struct
import termios
import time
from dataclasses import dataclass, field

import serial

MAGIC = b"\x02\x01\x04\x03\x06\x05\x08\x07"
HEADER = struct.Struct("<4H8I")
TL = struct.Struct("<II")
PLATFORM_XWRL6844 = 0xA6844
MAX_PACKET_LEN = 1 << 20  # sanity bound used for resync

# TLV types (MmwDemo_output_message_type in mmwave_demo.h)
TLV_DETECTED_POINTS = 1
TLV_RANGE_PROFILE = 2
TLV_RANGE_DOPPLER_HEAT_MAP = 5
TLV_DETECTED_POINTS_SIDE_INFO = 7
TLV_EXT_STATS = 306
TLV_EXT_RX_CHAN_COMPENSATION_INFO = 318

TLV_NAMES = {
    TLV_DETECTED_POINTS: "points",
    TLV_RANGE_PROFILE: "range_profile",
    TLV_RANGE_DOPPLER_HEAT_MAP: "range_doppler",
    TLV_DETECTED_POINTS_SIDE_INFO: "side_info",
    TLV_EXT_STATS: "stats",
    TLV_EXT_RX_CHAN_COMPENSATION_INFO: "rx_chan_comp",
}

POINT = struct.Struct("<4f")      # DPIF_PointCloudCartesian: x, y, z (m), velocity (m/s)
# DPIF_PointCloudSideInfo: snr, noise. Header says 0.1 dB steps, but the demo
# scales by 10 twice (CFARDSP_CONV_PEAK_TO_LOG already includes *10, then
# dpc.c multiplies by 10 again), so the wire value is in 0.01 dB.
SIDE_INFO = struct.Struct("<2h")
SIDE_INFO_DB_PER_LSB = 0.01

# Range profile / heatmap values are the log2 detection matrix in Q8:
# dB = raw * 6 / 256 (relative, uncalibrated)
DETMATRIX_DB_PER_LSB = 6.0 / 256
STATS = struct.Struct("<II4H4h")  # MmwDemo_output_message_stats


@dataclass
class Stats:
    inter_frame_processing_us: int
    transmit_output_us: int
    power_mw: tuple       # 1.8V, 3.3V, 1.2V, 1.2V RF rails in mW (None = not measured)
    temp_c: tuple         # avg Rx, avg Tx, PM, DIG


@dataclass
class Frame:
    version: int
    platform: int
    frame_number: int
    num_detected_obj: int
    num_tlvs: int
    points: list = field(default_factory=list)       # [(x, y, z, v), ...]
    side_info: list = field(default_factory=list)    # [(snr_db, noise_db), ...]
    range_profile: list | None = None                # raw uint16 per range bin (x DETMATRIX_DB_PER_LSB = dB)
    range_doppler: list | None = None                # raw uint16, flat (range-major), same units
    stats: Stats | None = None
    unknown_tlvs: dict = field(default_factory=dict) # type -> payload bytes

    @property
    def version_str(self):
        v = self.version
        return f"{v >> 24 & 0xFF:02d}.{v >> 16 & 0xFF:02d}.{v >> 8 & 0xFF:02d}.{v & 0xFF:02d}"


def open_port(port, baud, timeout=0.1):
    """Open a serial port, including non-standard rates like the 1250000 data UART.

    pyserial 3.5 hands BOTHER to termios.tcsetattr() for custom rates, which
    glibc >= 2.42 rejects with EINVAL. Open at a standard rate, then set the
    real rate with pyserial's TCSETS2/BOTHER ioctl, which the kernel accepts.
    """
    if hasattr(termios, f"B{baud}"):
        return serial.Serial(port, baud, timeout=timeout)
    ser = serial.Serial(port, 115200, timeout=timeout)
    # Leaves pyserial believing it's at 115200; don't change port settings later
    ser._set_special_baudrate(baud)
    return ser


def parse_packet(packet):
    """Parse one complete packet (header + TLVs + padding) into a Frame."""
    (_m0, _m1, _m2, _m3, version, _total_len, platform, frame_number,
     _cpu_cycles, num_obj, num_tlvs, _subframe) = HEADER.unpack_from(packet, 0)
    frame = Frame(version, platform, frame_number, num_obj, num_tlvs)

    off = HEADER.size
    for _ in range(num_tlvs):
        if off + TL.size > len(packet):
            raise ValueError("TLV header runs past end of packet")
        tlv_type, length = TL.unpack_from(packet, off)
        off += TL.size
        payload = packet[off:off + length]
        if len(payload) != length:
            raise ValueError(f"TLV {tlv_type} payload runs past end of packet")
        off += length

        if tlv_type == TLV_DETECTED_POINTS:
            frame.points = list(POINT.iter_unpack(payload))
        elif tlv_type == TLV_DETECTED_POINTS_SIDE_INFO:
            frame.side_info = [(s * SIDE_INFO_DB_PER_LSB, n * SIDE_INFO_DB_PER_LSB)
                               for s, n in SIDE_INFO.iter_unpack(payload)]
        elif tlv_type == TLV_RANGE_PROFILE:
            frame.range_profile = list(struct.unpack(f"<{length // 2}H", payload))
        elif tlv_type == TLV_RANGE_DOPPLER_HEAT_MAP:
            frame.range_doppler = list(struct.unpack(f"<{length // 2}H", payload))
        elif tlv_type == TLV_EXT_STATS:
            proc_us, tx_us, *rest = STATS.unpack(payload)
            # 0xFFFF means the rail wasn't measured (seen when USB-powered)
            power = tuple(None if p == 0xFFFF else p / 10 for p in rest[:4])
            frame.stats = Stats(proc_us, tx_us, power, tuple(rest[4:]))
        else:
            frame.unknown_tlvs[tlv_type] = bytes(payload)
    return frame


class FrameParser:
    """Incremental parser: feed() raw bytes, get back complete Frames.

    Resyncs on the magic word, so it tolerates starting mid-stream and
    dropped bytes. Counters `resyncs` and `bad_packets` show stream health.
    """

    def __init__(self):
        self.buf = bytearray()
        self.resyncs = 0
        self.bad_packets = 0

    def feed(self, data):
        self.buf += data
        frames = []
        while True:
            start = self.buf.find(MAGIC)
            if start < 0:
                # keep a tail in case the magic word is split across reads
                del self.buf[:max(0, len(self.buf) - len(MAGIC) + 1)]
                break
            if start > 0:
                self.resyncs += 1
                del self.buf[:start]
            if len(self.buf) < HEADER.size:
                break
            total_len = HEADER.unpack_from(self.buf, 0)[5]
            if total_len < HEADER.size or total_len > MAX_PACKET_LEN:
                self.bad_packets += 1
                del self.buf[:len(MAGIC)]
                continue
            if len(self.buf) < total_len:
                break
            packet = bytes(self.buf[:total_len])
            del self.buf[:total_len]
            try:
                frames.append(parse_packet(packet))
            except (ValueError, struct.error):
                self.bad_packets += 1
        return frames


# --- CLI ---------------------------------------------------------------------

# The demo CLI ends every command's reply with one of these
_CLI_END = re.compile(rb"Done|Error -?\d+|is not recognized as a CLI command|Skipped")
CLI_PROMPT = b"mmwDemo:/>"
SLOW_COMMANDS =("sensorStart", "factoryCalibCfg", "sensorStop")


def read_cfg_lines(path):
    """Commands from a .cfg file, skipping blank lines and % comments."""
    with open(path) as f:
        return read_cfg_lines_from_text(f.read())


def read_cfg_lines_from_text(text):
    return [s for s in (line.strip() for line in text.splitlines()) if s and not s.startswith("%")]


CHAR_GAP_S = 0.0005  # pace typed characters; the CLI polls its UART and drops bytes when busy


def _wait_for_prompt(cli, reply, start, seconds=1.0):
    deadline = time.monotonic() + seconds
    while CLI_PROMPT not in reply[start:] and time.monotonic() < deadline:
        reply += cli.read(cli.in_waiting or 1)


def send_command(cli, command, timeout=3.0, attempts=3):
    """Send one CLI command and return (ok, reply_text).

    The CLI echoes what it received. If the echo doesn't contain the command, bytes
    were dropped (the device was busy) and the mangled line can't have run as this
    command, so it is resent. A cleanly received command is never resent.
    """
    text = ""
    for _ in range(attempts):
        cli.reset_input_buffer()
        for b in (command + "\n").encode():
            cli.write(bytes([b]))
            time.sleep(CHAR_GAP_S)
        deadline = time.monotonic() + timeout
        reply = bytearray()
        m = None
        while time.monotonic() < deadline:
            reply += cli.read(cli.in_waiting or 1)
            m = _CLI_END.search(reply)
            # a fresh prompt with no status means the line arrived empty or mangled
            if m or CLI_PROMPT in reply:
                break
        text = reply.decode(errors="replace").replace("\r", "")
        if not reply:
            return False, text + " [timeout]"  # nothing at all: device isn't answering
        if m and command in text:
            # The CLI isn't reading input until it has printed its prompt again;
            # bytes sent before that are dropped, so wait for it.
            _wait_for_prompt(cli, reply, m.end())
            time.sleep(0.01)
            return m.group(0) == b"Done", reply.decode(errors="replace")
        _wait_for_prompt(cli, reply, m.end() if m else 0)
        time.sleep(0.05)
    return False, text + f" [no clean echo after {attempts} attempts]"


def send_cfg(cli_port, commands, baud=115200, on_reply=None):
    """Send a list of CLI commands. Stops at the first failure. Returns True if all succeeded."""
    with serial.Serial(cli_port, baud, timeout=0.05) as cli:
        for command in commands:
            timeout = 15.0 if command.startswith(SLOW_COMMANDS) else 3.0
            ok, reply = send_command(cli, command, timeout)
            if on_reply:
                on_reply(command, ok, reply)
            if not ok:
                return False
    return True

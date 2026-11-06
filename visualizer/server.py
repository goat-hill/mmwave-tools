#!/usr/bin/env python3
"""Backend for the OOB demo visualizer.

Owns the two serial ports, sends cfgs, records raw logs, replays them, and pushes
parsed frames to browsers over a WebSocket. Serves the built frontend (web/dist)
when present; during frontend development use `npm run dev` in web/, which proxies
/api and /ws here.

  ../.venv/bin/python server.py            # http://127.0.0.1:8765
"""
import argparse
import asyncio
import glob
import json
import os
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path

import serial
import serial.tools.list_ports
from aiohttp import WSMsgType, web

import cfg_info
import oob_protocol as oob

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LOG_DIR = REPO / "logs"
LOCAL_CFG_DIR = REPO / "cfgs"
DIST_DIR = HERE / "web" / "dist"
SDK_PROFILES = "examples/mmw_demo/mmwave_demo/profiles"
XDS110_VID_PID = (0x0451, 0xBEF3)
DATA_BAUD = 1250000


def find_sdk(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("MMWAVE_SDK"):
        return Path(os.environ["MMWAVE_SDK"]).expanduser()
    found = sorted(glob.glob(os.path.expanduser("~/ti/MMWAVE_L_SDK_*/mmwave_l_sdk_*")))
    return Path(found[-1]) if found else None


def sdk_version(sdk):
    m = re.search(r"(\d\d)_(\d\d)_(\d\d)_(\d\d)$", str(sdk or ""))
    return ".".join(m.groups()) if m else None


def detect_ports():
    """(cli, data) device paths for the first XDS110 found, else (None, None).

    The XDS110 exposes the Application/User UART on USB interface 0 and the
    Auxiliary Data Port on interface 3.
    """
    cli = data = None
    for p in serial.tools.list_ports.comports():
        if (p.vid, p.pid) != XDS110_VID_PID:
            continue
        iface = (p.location or "").rsplit(".", 1)[-1]
        if iface == "0" and cli is None:
            cli = p.device
        elif iface == "3" and data is None:
            data = p.device
    return cli, data


def frame_message(frame, num_range_bins=None, source="live"):
    msg = {
        "type": "frame",
        "source": source,
        "frame": frame.frame_number,
        "version": frame.version_str,
        "platform": f"0x{frame.platform:X}",
        "points": [
            [round(x, 3), round(y, 3), round(z, 3), round(v, 3), round(snr, 2), round(noise, 2)]
            for (x, y, z, v), (snr, noise) in zip(frame.points, frame.side_info)
        ],
        "rangeProfile": None,
        "rangeDoppler": None,
        "stats": None,
    }
    if frame.range_profile:
        msg["rangeProfile"] = [round(r * oob.DETMATRIX_DB_PER_LSB, 2) for r in frame.range_profile]
        num_range_bins = len(frame.range_profile)
    if frame.range_doppler and num_range_bins:
        cols = len(frame.range_doppler) // num_range_bins
        msg["rangeDoppler"] = {
            "rows": num_range_bins,
            "cols": cols,
            "data": [round(r * oob.DETMATRIX_DB_PER_LSB, 1) for r in frame.range_doppler[:num_range_bins * cols]],
        }
    if frame.stats:
        s = frame.stats
        msg["stats"] = {
            "procUs": s.inter_frame_processing_us,
            "uartUs": s.transmit_output_us,
            "powerMw": list(s.power_mw),
            "tempC": list(s.temp_c),
        }
    return msg


class Hub:
    """Shared state: serial ports, recording, replay, and connected browsers."""

    def __init__(self, loop, sdk, cli_port=None, data_port=None):
        self.loop = loop
        self.sdk = sdk
        self.cli_port_override = cli_port
        self.data_port_override = data_port
        self.clients = set()
        self.queue = asyncio.Queue(maxsize=200)

        self.cli_port = self.data_port = None
        self.data_ser = None
        self.reader_thread = None
        self.reader_stop = threading.Event()
        self.cli_lock = threading.Lock()
        self.parser = oob.FrameParser()

        self.record_lock = threading.Lock()
        self.record_file = None
        self.record_path = None

        self.replay_task = None
        self.replay_path = None

        self.active_cfg = None
        self.active_info = None
        self.sending_cfg = False
        self.last_frame_time = None
        self.device_version = None

    # --- messaging --------------------------------------------------------

    def post(self, msg):
        """Thread-safe: queue a message for all browsers."""
        def put():
            if self.queue.full():
                self.queue.get_nowait()  # drop the oldest rather than block
            self.queue.put_nowait(msg)
        self.loop.call_soon_threadsafe(put)

    async def broadcast_loop(self):
        while True:
            msg = await self.queue.get()
            text = json.dumps(msg)
            for ws in list(self.clients):
                try:
                    await ws.send_str(text)
                except ConnectionError:
                    self.clients.discard(ws)

    def status(self):
        return {
            "type": "status",
            "connected": self.data_ser is not None,
            "cliPort": self.cli_port,
            "dataPort": self.data_port,
            "recording": self.record_path.name if self.record_path else None,
            "replaying": self.replay_path.name if self.replay_path else None,
            "activeCfg": self.active_cfg,
            "cfgInfo": asdict(self.active_info) if self.active_info else None,
            "sendingCfg": self.sending_cfg,
            "sdkVersion": sdk_version(self.sdk),
            "deviceVersion": self.device_version,
        }

    def post_status(self):
        self.post(self.status())

    def post_error(self, text):
        self.post({"type": "error", "message": text})

    def num_range_bins(self):
        return self.active_info.num_range_bins if self.active_info else None

    # --- serial -----------------------------------------------------------

    def connect(self, cli_port=None, data_port=None):
        if self.data_ser:
            return
        auto_cli, auto_data = detect_ports()
        self.cli_port = cli_port or self.cli_port_override or auto_cli
        self.data_port = data_port or self.data_port_override or auto_data
        if not (self.cli_port and self.data_port):
            raise RuntimeError("XDS110 ports not found; is the EVM plugged in?")
        self.data_ser = oob.open_port(self.data_port, DATA_BAUD)
        self.data_ser.reset_input_buffer()
        self.parser = oob.FrameParser()
        self.reader_stop.clear()
        self.reader_thread = threading.Thread(target=self._read_data, daemon=True)
        self.reader_thread.start()

    def disconnect(self):
        self.reader_stop.set()
        if self.reader_thread:
            self.reader_thread.join(timeout=1)
        if self.data_ser:
            self.data_ser.close()
        self.data_ser = None
        self.reader_thread = None

    def _read_data(self):
        ser = self.data_ser
        try:
            while not self.reader_stop.is_set():
                data = ser.read(4096)
                if not data:
                    continue
                with self.record_lock:
                    if self.record_file:
                        self.record_file.write(data)
                for frame in self.parser.feed(data):
                    self._on_frame(frame)
        except (serial.SerialException, OSError) as e:
            self.post_error(f"data port error: {e}")
            self.data_ser = None
            ser.close()
            self.post_status()

    def _on_frame(self, frame):
        self.last_frame_time = time.monotonic()
        if self.device_version != frame.version_str:
            self.device_version = frame.version_str
            self.post_status()
        if self.replay_path:
            return  # don't mix live frames into a replay (recording still captures them)
        self.post(frame_message(frame, self.num_range_bins()))

    def send_cfg(self, name, text):
        """Blocking; run in a thread. Streams each command's reply to browsers."""
        try:
            info = cfg_info.cfg_info(text)
        except (KeyError, ValueError, IndexError):
            info = None  # e.g. a monitors-only cfg; send it anyway

        def on_reply(command, ok, reply):
            self.post({"type": "cli", "command": command, "ok": ok, "reply": reply})

        self.sending_cfg = True
        self.post_status()
        try:
            with self.cli_lock:
                ok = oob.send_cfg(self.cli_port, oob.read_cfg_lines_from_text(text), on_reply=on_reply)
        except serial.SerialException as e:
            ok = False
            self.post_error(f"CLI port error: {e}")
        finally:
            self.sending_cfg = False
        if ok:
            self.active_cfg = name
            if info:
                self.active_info = info
        else:
            self.post_error("cfg failed; if the sensor is already running, press the EVM reset button and retry")
        self.post_status()

    def send_command(self, command):
        try:
            with self.cli_lock, serial.Serial(self.cli_port, 115200, timeout=0.05) as cli:
                ok, reply = oob.send_command(cli, command, timeout=5.0)
        except serial.SerialException as e:
            self.post_error(f"CLI port error: {e}")
            return
        self.post({"type": "cli", "command": command, "ok": ok, "reply": reply})

    # --- recording / replay -------------------------------------------------

    def start_recording(self):
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / time.strftime("frameData-%Y%m%d-%H%M%S.bin")
        with self.record_lock:
            self.record_file = open(path, "wb")
            self.record_path = path

    def stop_recording(self):
        with self.record_lock:
            if self.record_file:
                self.record_file.close()
            self.record_file = None
            self.record_path = None

    async def replay(self, path, period_s):
        """Feed a raw log through the parser, one frame per period."""
        self.replay_path = path
        self.post_status()
        parser = oob.FrameParser()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(4096):
                    for frame in parser.feed(chunk):
                        self.post(frame_message(frame, self.num_range_bins(), source="replay"))
                        await asyncio.sleep(period_s)
        finally:
            # a newer replay may have replaced this one; only the current task clears state
            if self.replay_task is asyncio.current_task():
                self.replay_path = None
                self.replay_task = None
                self.post_status()


# --- cfg listing ---------------------------------------------------------------

def list_cfgs(sdk):
    out = []
    if sdk and (sdk / SDK_PROFILES).is_dir():
        out += [{"name": f"sdk/{p.name}", "source": "sdk"} for p in sorted((sdk / SDK_PROFILES).glob("*.cfg"))]
    if LOCAL_CFG_DIR.is_dir():
        out += [{"name": f"local/{p.name}", "source": "local"} for p in sorted(LOCAL_CFG_DIR.glob("*.cfg"))]
    return out


def resolve_cfg(sdk, name):
    source, _, fname = name.partition("/")
    if "/" in fname or fname.startswith("."):
        raise web.HTTPBadRequest(text="bad cfg name")
    base = {"sdk": sdk / SDK_PROFILES if sdk else None, "local": LOCAL_CFG_DIR}.get(source)
    path = base / fname if base else None
    if not path or not path.is_file():
        raise web.HTTPNotFound(text=f"no such cfg: {name}")
    return path


def info_or_none(text):
    try:
        return asdict(cfg_info.cfg_info(text))
    except (KeyError, ValueError, IndexError):
        return None


# --- HTTP / WebSocket handlers ---------------------------------------------------

async def api_ports(request):
    cli, data = detect_ports()
    ports = [{"device": p.device, "description": p.description, "location": p.location}
             for p in serial.tools.list_ports.comports() if p.vid is not None]  # USB only
    return web.json_response({"cli": cli, "data": data, "ports": ports})


async def api_cfgs(request):
    return web.json_response(list_cfgs(request.app["hub"].sdk))


async def api_cfg(request):
    path = resolve_cfg(request.app["hub"].sdk, request.query.get("name", ""))
    text = path.read_text()
    return web.json_response({"name": request.query["name"], "text": text, "info": info_or_none(text)})


async def api_cfg_info(request):
    text = await request.text()
    return web.json_response({"info": info_or_none(text)})


async def api_logs(request):
    LOG_DIR.mkdir(exist_ok=True)
    logs = sorted(LOG_DIR.glob("*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)
    return web.json_response([{"name": p.name, "bytes": p.stat().st_size} for p in logs])


async def ws_handler(request):
    hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    hub.clients.add(ws)
    await ws.send_str(json.dumps(hub.status()))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                await handle_command(hub, json.loads(msg.data))
            except Exception as e:  # report to the UI instead of dropping the socket
                hub.post_error(str(e))
    finally:
        hub.clients.discard(ws)
    return ws


async def handle_command(hub, cmd):
    kind = cmd.get("type")
    run = asyncio.get_running_loop().run_in_executor

    if kind == "connect":
        await run(None, hub.connect, cmd.get("cliPort"), cmd.get("dataPort"))
    elif kind == "disconnect":
        hub.stop_recording()
        await run(None, hub.disconnect)
    elif kind == "sendCfg":
        if cmd.get("text") is not None:
            name, text = cmd.get("name") or "uploaded.cfg", cmd["text"]
        else:
            name = cmd["name"]
            text = resolve_cfg(hub.sdk, name).read_text()
        if not hub.data_ser:
            await run(None, hub.connect)  # catch the first frames
        run(None, hub.send_cfg, name, text)
    elif kind == "command":
        if not hub.cli_port:
            hub.cli_port = hub.cli_port_override or detect_ports()[0]
        run(None, hub.send_command, cmd["text"])
    elif kind == "record":
        hub.start_recording() if cmd.get("on") else hub.stop_recording()
    elif kind == "replay":
        if hub.replay_task:
            hub.replay_task.cancel()
        name = Path(cmd["name"]).name  # logs/ only
        path = LOG_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"no such log: {name}")
        period = float(cmd.get("periodMs", 100)) / 1000
        hub.replay_task = asyncio.create_task(hub.replay(path, period))
        return
    elif kind == "stopReplay":
        if hub.replay_task:
            hub.replay_task.cancel()
        return
    hub.post_status()


async def index(request):
    return web.FileResponse(DIST_DIR / "index.html")


def make_app(args):
    app = web.Application()

    async def on_startup(app):
        hub = Hub(asyncio.get_running_loop(), find_sdk(args.sdk), args.cli, args.data)
        app["hub"] = hub
        app["broadcaster"] = asyncio.create_task(hub.broadcast_loop())
        if hub.sdk is None:
            print("warning: SDK not found; set MMWAVE_SDK or pass --sdk (preset cfgs unavailable)")

    async def on_shutdown(app):
        # close browser sockets now instead of waiting out aiohttp's shutdown timeout
        for ws in list(app["hub"].clients):
            await ws.close(code=1001, message=b"server shutdown")

    async def on_cleanup(app):
        hub = app["hub"]
        hub.stop_recording()
        hub.disconnect()
        app["broadcaster"].cancel()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/api/ports", api_ports)
    app.router.add_get("/api/cfgs", api_cfgs)
    app.router.add_get("/api/cfg", api_cfg)
    app.router.add_post("/api/cfg-info", api_cfg_info)
    app.router.add_get("/api/logs", api_logs)
    app.router.add_get("/ws", ws_handler)
    if DIST_DIR.is_dir():
        app.router.add_get("/", index)
        app.router.add_static("/", DIST_DIR)
    return app


def main():
    ap = argparse.ArgumentParser(description="OOB demo visualizer backend")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sdk", help="SDK root (default: $MMWAVE_SDK or newest ~/ti/MMWAVE_L_SDK_*)")
    ap.add_argument("--cli", help="CLI port (default: auto-detect XDS110 interface 0)")
    ap.add_argument("--data", help="data port (default: auto-detect XDS110 interface 3)")
    args = ap.parse_args()
    LOCAL_CFG_DIR.mkdir(exist_ok=True)
    print(f"serving on http://{args.host}:{args.port}"
          + ("" if DIST_DIR.is_dir() else "  (no web/dist yet: run `npm run dev` in web/)"))
    web.run_app(make_app(args), host=args.host, port=args.port, print=None, shutdown_timeout=2)


if __name__ == "__main__":
    main()

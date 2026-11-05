#!/usr/bin/env python3
"""Extract TI's xWRL6844 flasher (arprog_cmdline_6844.exe) so it can run on Linux.

The .exe is a PyInstaller bundle of Python 3.12 bytecode. This script only
*reads* the bundle and writes out the two pieces we need:

  extracted/arprog_cmdline_6844.marshal   main script (CLI args + flash sequence)
  extracted/arprog_6844.pyc               BootLdr class (UART bootloader protocol)

It never executes TI's code. The bundled Windows copy of pyserial is skipped on
purpose so the venv's Linux pyserial is used instead.

Usage:
  python3 extract_arprog.py [path/to/arprog_cmdline_6844.exe]

If no path is given, $MMWAVE_SDK/tools/FlashingTool/arprog_cmdline_6844.exe is used.
"""
import marshal
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "extracted")

# PyInstaller CArchive "cookie" magic, found near the end of the exe
COOKIE_MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
MAIN_SCRIPT = "arprog_cmdline_6844"
MODULES = ["arprog_6844"]


def default_exe():
    sdk = os.environ.get("MMWAVE_SDK")
    if not sdk:
        sys.exit("error: pass the exe path or set MMWAVE_SDK to the SDK root "
                 "(the folder containing tools/ and examples/)")
    return os.path.join(sdk, "tools", "FlashingTool", "arprog_cmdline_6844.exe")


def read_carchive(data):
    """Return {name: (typecode, bytes)} for every entry in the PyInstaller archive."""
    ci = data.rfind(COOKIE_MAGIC)
    if ci < 0:
        sys.exit("error: not a PyInstaller executable (cookie not found)")
    pkg_len, toc_off, toc_len, pyver = struct.unpack("!IIIi", data[ci + 8:ci + 24])
    if pyver != 312:
        print(f"warning: bundle was built for Python {pyver // 100}.{pyver % 100}, "
              "not 3.12; use a matching interpreter in the venv")
    start = ci + 88 - pkg_len
    toc = data[start + toc_off:start + toc_off + toc_len]

    entries = {}
    p = 0
    while p < len(toc):
        entry_size, pos, csize, _usize, compressed, typecode = struct.unpack("!IIIIBc", toc[p:p + 18])
        name = toc[p + 18:p + entry_size].rstrip(b"\0").decode()
        p += entry_size
        blob = data[start + pos:start + pos + csize]
        if compressed:
            blob = zlib.decompress(blob)
        entries[name] = (typecode.decode(), blob)
    return entries


def read_pyz(blob):
    """Return (pyc_magic, {module_name: marshalled_code_bytes}) from a PYZ archive."""
    if blob[:4] != b"PYZ\0":
        sys.exit("error: PYZ archive has an unexpected header")
    pyc_magic = blob[4:8]
    (toc_off,) = struct.unpack("!I", blob[8:12])
    toc = marshal.loads(blob[toc_off:])  # plain list/tuple of str/int: version independent
    if isinstance(toc, dict):
        toc = list(toc.items())
    modules = {}
    for name, (_typecode, pos, length) in toc:
        modules[name] = blob[pos:pos + length]
    return pyc_magic, modules


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else default_exe()
    with open(exe, "rb") as f:
        data = f.read()

    entries = read_carchive(data)

    if MAIN_SCRIPT not in entries:
        sys.exit(f"error: {MAIN_SCRIPT} not found in bundle")
    pyz_name = next((n for n, (t, _) in entries.items() if t == "z"), None)
    if pyz_name is None:
        sys.exit("error: no PYZ archive in bundle")
    pyc_magic, modules = read_pyz(entries[pyz_name][1])

    os.makedirs(OUT_DIR, exist_ok=True)

    main_path = os.path.join(OUT_DIR, MAIN_SCRIPT + ".marshal")
    with open(main_path, "wb") as f:
        f.write(entries[MAIN_SCRIPT][1])
    print(f"wrote {main_path}")

    for mod in MODULES:
        if mod not in modules:
            sys.exit(f"error: module {mod} not found in PYZ")
        code = zlib.decompress(modules[mod])
        # 16-byte .pyc header: magic, flags=0, mtime=0, size=0. Sourceless
        # imports don't validate the timestamp, so zeros are fine.
        mod_path = os.path.join(OUT_DIR, mod + ".pyc")
        with open(mod_path, "wb") as f:
            f.write(pyc_magic + b"\0" * 12 + code)
        print(f"wrote {mod_path}")


if __name__ == "__main__":
    main()

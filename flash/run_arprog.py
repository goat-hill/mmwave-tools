#!/usr/bin/env python3
"""Run TI's extracted arprog_cmdline_6844 flasher on Linux.

Does what the .exe's PyInstaller bootstrap does on Windows: puts the extracted
modules on the import path, then executes the main script with our arguments.
Must be run with Python 3.12 (the bytecode's version), i.e. the uv venv.

Usage (same arguments as arprog_cmdline_6844.exe, but /dev/ttyACM0 instead of COMxx):
  ../.venv/bin/python run_arprog.py -p /dev/ttyACM0 -f1 <app>.appimage -s SFLASH -c -cf
"""
import marshal
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACTED = os.path.join(HERE, "extracted")
MAIN = os.path.join(EXTRACTED, "arprog_cmdline_6844.marshal")

if sys.version_info[:2] != (3, 12):
    sys.exit(f"error: needs Python 3.12, this is {sys.version.split()[0]}. "
             "Run with ../.venv/bin/python")
if not os.path.isfile(MAIN):
    sys.exit("error: extracted files missing; run extract_arprog.py first")

# Append (not prepend) so the venv's pyserial/idna always win over anything here
sys.path.append(EXTRACTED)

with open(MAIN, "rb") as f:
    code = marshal.load(f)

sys.argv[0] = "arprog_cmdline_6844"
exec(code, {"__name__": "__main__", "__builtins__": __builtins__})

#!/usr/bin/env python3
"""Record a LanEx SSE stream to a file, one timestamped line per event line.

usage: sse_capture.py <url> <outfile> <timeout_seconds>
Stops on a terminal flow event (flow_done / flow_failed / flow_cancelled) or on
timeout. Importable: ``capture(url, outfile, timeout)`` for in-process use.
"""
from __future__ import annotations

import sys
import time
import urllib.request


def capture(url: str, out: str, timeout: float) -> None:
    t0 = time.time()
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    with open(out, "a", encoding="utf-8") as fh, urllib.request.urlopen(req, timeout=30) as resp:
        fh.write(f"# capture start {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        while time.time() - t0 < timeout:
            try:
                line = resp.readline()
            except Exception as ex:  # noqa: BLE001 - record and stop, never raise
                fh.write(f"# READ_ERROR {ex}\n")
                fh.flush()
                return
            if not line:
                fh.write("# STREAM_CLOSED\n")
                return
            txt = line.decode("utf-8", "replace").rstrip("\n")
            fh.write(f"{time.time() - t0:9.2f}s {txt}\n")
            fh.flush()
            if '"flow_done"' in txt or '"flow_failed"' in txt or '"flow_cancelled"' in txt:
                fh.write("# terminal event seen\n")
                return
        fh.write("# TIMEOUT\n")


def main(argv: list | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 1
    capture(argv[0], argv[1], float(argv[2]))
    print("capture finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())

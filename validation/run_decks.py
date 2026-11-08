#!/usr/bin/env python3
"""Run the Task-1 requirements-critical GEOS decks and record pass/fail.

The decks are executed from a throwaway copy of ``GEOS/inputFiles`` so that
GEOS output files never touch the upstream clone. Each run is a fresh
container of the same TPL image used to build GEOS.

Usage
-----
    python3 validation/run_decks.py --jobs 4 --timeout 240
    python3 validation/run_decks.py --only singlePhaseFlowFractures
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import hashlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                       # integration workspace
GEOS = ROOT / "GEOS"
INPUTS = GEOS / "inputFiles"
WORK = ROOT / "geos-tests"
TREE = WORK / "tree"
LOGS = WORK / "logs"
RESULTS = WORK / "results.jsonl"
IMAGE = "geosx/ubuntu24.04-gcc13:364-1112"
GEOS_BIN = "/work/geos-build/bin/geosx"

_lock = threading.Lock()


def prepare_tree() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    if TREE.exists():
        return
    print(f"copying {INPUTS} -> {TREE} ...", flush=True)
    shutil.copytree(INPUTS, TREE)


def classify(rc: int, out: str, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    if rc == 0 and "***** ERROR" not in out:
        return "pass"
    if "not a recognized extension" in out or "Could not open" in out:
        return "missing-file"
    if "XML" in out and ("schema" in out or "validation" in out):
        return "xml-error"
    return "fail"


def error_excerpt(out: str, n: int = 6) -> str:
    lines = [l.rstrip() for l in out.splitlines() if l.strip()]
    err = [i for i, l in enumerate(lines)
           if "ERROR" in l or "Error" in l or "error" in l]
    if not err:
        return " | ".join(lines[-n:])[:600]
    i = err[-1]
    return " | ".join(lines[max(0, i - 1):i + n])[:600]


def run_one(deck: str, timeout: int, user: str) -> dict:
    d = TREE / Path(deck).parent
    log = LOGS / (deck.replace("/", "__") + ".log")
    name = "geosval-" + hashlib.md5(deck.encode()).hexdigest()[:12]
    cmd = [
        "docker", "run", "--rm", "--name", name, "--user", user,
        "-e", "HOME=/tmp",
        "-v", f"{ROOT}:/work", "-w", f"/work/geos-tests/tree/{Path(deck).parent}",
        IMAGE, GEOS_BIN, "-i", Path(deck).name,
    ]
    t0 = time.time()
    timed_out = False
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        raw = (e.stdout or b"") + (e.stderr or b"")
        out = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        # subprocess.run only kills the docker client; stop the container too
        subprocess.run(["docker", "kill", name], capture_output=True)
        rc, timed_out = -1, True
    dt = round(time.time() - t0, 1)
    log.write_text(out[-2_000_000:])

    produced = []
    for pat in ("*.vtu", "*.pvd", "*.hdf5", "*.vtk"):
        produced += [p.name for p in d.glob(pat)]
    status = classify(rc, out, timed_out)
    return {
        "deck": deck,
        "status": status,
        "rc": rc,
        "seconds": dt,
        "outputs": len(produced),
        "error": "" if status == "pass" else error_excerpt(out),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--selection", default=str(WORK / "selection.json"))
    args = ap.parse_args()

    rows = json.loads(Path(args.selection).read_text())
    decks = [r["deck"] for r in rows if r["runnable"]]
    if args.only:
        decks = [d for d in decks if args.only in d]
    if args.limit:
        decks = decks[:args.limit]
    if not (ROOT / "geos-build" / "bin" / "geosx").exists():
        print("ERROR: geos binary not built at", ROOT / "geos-build/bin/geosx")
        return 2

    prepare_tree()
    user = f"{os.getuid()}:{os.getgid()}"
    print(f"running {len(decks)} decks, jobs={args.jobs}, timeout={args.timeout}s",
          flush=True)

    done = 0
    with RESULTS.open("a") as fh, ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(run_one, d, args.timeout, user): d for d in decks}
        for fut in as_completed(futs):
            r = fut.result()
            with _lock:
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                done += 1
                mark = {"pass": "PASS", "fail": "FAIL", "timeout": "TIME",
                        "xml-error": "XML ", "missing-file": "MISS"}[r["status"]]
                print(f"[{done:3d}/{len(decks)}] {mark} {r['seconds']:7.1f}s "
                      f"{r['deck']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

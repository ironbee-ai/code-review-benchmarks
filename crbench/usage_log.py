"""Reading the judge proxy's usage logs (results/judge_usage/<judge>.jsonl, one JSON row per call). A line that is
not a JSON object is skipped and counted: on 2026-10-17 at 23:58 local, Sol's log got ~790 bytes of TLS ciphertext
between two rows (a socket write that landed on the log file's descriptor, a proxy fault fixed before pass 3)."""
from __future__ import annotations

import json
from pathlib import Path


def read_rows(path: Path | str) -> tuple[list[dict], int]:
    """The log's rows, and how many lines were not a JSON object."""
    rows: list[dict] = []
    bad = 0
    for raw in Path(path).read_bytes().split(b"\n"):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad

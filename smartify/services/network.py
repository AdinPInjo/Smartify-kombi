"""
Network helpers for nmcli-based endpoints.
"""
import subprocess
from typing import List


def run_nmcli(args: List[str]) -> subprocess.CompletedProcess:
    cmd = ["nmcli"] + args
    return subprocess.run(cmd, capture_output=True, text=True)

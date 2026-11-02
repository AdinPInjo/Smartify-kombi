"""Monthly GPX archive of the GPS track.

Before history pruning deletes GPS points older than the retention period,
they are written to ``data/archive/gps/YYYY-MM.gpx``: one track per day. GPX
opens directly in Komoot, Strava, Google Earth, GPX editors and video tools.

Pruning runs every few hours, so a month file is updated several times; each
update merges the new points into what the file already holds.
"""

from __future__ import annotations

import calendar
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

GPX_NS = "http://www.topografix.com/GPX/1/1"
_NAME = re.compile(r"^\d{4}-\d{2}\.gpx$")

ET.register_namespace("", GPX_NS)


def archive_dir(data_dir: Path) -> Path:
    return data_dir / "archive" / "gps"


def is_archive_name(name: str) -> bool:
    return bool(_NAME.match(name))


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _parse_iso(value: str) -> int:
    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))


def _read_points(path: Path) -> dict[int, tuple[float, float, float | None]]:
    """Existing points by timestamp (so re-archiving is idempotent)."""
    points: dict[int, tuple[float, float, float | None]] = {}
    if not path.exists():
        return points
    root = ET.parse(path).getroot()
    for pt in root.iter(f"{{{GPX_NS}}}trkpt"):
        when = pt.find(f"{{{GPX_NS}}}time")
        ele = pt.find(f"{{{GPX_NS}}}ele")
        if when is None or when.text is None:
            continue
        points[_parse_iso(when.text)] = (
            float(pt.get("lat")),
            float(pt.get("lon")),
            float(ele.text) if ele is not None and ele.text else None,
        )
    return points


def _write(path: Path, points: dict[int, tuple[float, float, float | None]]) -> None:
    gpx = ET.Element(f"{{{GPX_NS}}}gpx", {"version": "1.1", "creator": "Smartify Kombi"})
    by_day: dict[str, list[int]] = defaultdict(list)
    for ts in sorted(points):
        by_day[time.strftime("%Y-%m-%d", time.localtime(ts))].append(ts)
    for day, stamps in by_day.items():
        trk = ET.SubElement(gpx, f"{{{GPX_NS}}}trk")
        ET.SubElement(trk, f"{{{GPX_NS}}}name").text = day
        seg = ET.SubElement(trk, f"{{{GPX_NS}}}trkseg")
        for ts in stamps:
            lat, lon, ele = points[ts]
            pt = ET.SubElement(
                seg, f"{{{GPX_NS}}}trkpt", {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"}
            )
            if ele is not None:
                ET.SubElement(pt, f"{{{GPX_NS}}}ele").text = f"{ele:.1f}"
            ET.SubElement(pt, f"{{{GPX_NS}}}time").text = _iso(ts)
    ET.indent(gpx)
    tmp = path.with_suffix(".tmp")
    ET.ElementTree(gpx).write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)  # atomic: a power cut never leaves half a file


def archive_points(
    data_dir: Path, rows: list[tuple[float, float, float | None, int]]
) -> list[Path]:
    """Merge ``(lat, lon, altitude_m, created_at)`` rows into the month files."""
    by_month: dict[str, dict[int, tuple[float, float, float | None]]] = defaultdict(dict)
    for lat, lon, alt, ts in rows:
        by_month[time.strftime("%Y-%m", time.localtime(ts))][ts] = (lat, lon, alt)
    folder = archive_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for month, new_points in sorted(by_month.items()):
        path = folder / f"{month}.gpx"
        points = _read_points(path)
        points.update(new_points)
        _write(path, points)
        written.append(path)
    return written


def list_archives(data_dir: Path) -> list[dict]:
    folder = archive_dir(data_dir)
    if not folder.is_dir():
        return []
    return [
        {"name": p.name, "bytes": p.stat().st_size, "updated_at": int(p.stat().st_mtime)}
        for p in sorted(folder.glob("*.gpx"), reverse=True)
        if is_archive_name(p.name)
    ]

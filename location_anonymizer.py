"""Location data anonymizer.

Protects sensitive places (home, and optionally others) in a JSON location export by

1. removing every coordinate that falls inside a privacy zone around each protected
   place -- the zone centre is randomly displaced, so the hole left in the data is
   not centred on the place itself;
2. snapping every remaining coordinate to the centre of a grid cell;
3. auditing the result, and refusing to write anything if a protected place can
   still be found in it.

Coordinates are processed wherever they appear in the document, not only in the
``locations`` array. See the README for what this does and does not guarantee.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import math
import os
import secrets
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEG_LAT = 111.32

LAT_SUFFIXES = ("latitude", "lat")
LON_SUFFIXES = ("longitude", "long", "lng", "lon")

# The zone centre is displaced from the protected place by a distance between these
# two fractions of the zone radius. The lower bound keeps the centre itself away from
# the place; the upper bound keeps the place well inside the zone.
MIN_DISPLACEMENT = 0.2
MAX_DISPLACEMENT = 0.6

MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 5.0
MIN_GRID_M, MAX_GRID_M = 10.0, 5000.0

ZONE_MODES = ("drop", "snap")

_DROP = object()


class AnonymizationError(Exception):
    """Raised when the data cannot be anonymized safely. Nothing must be written."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def snap_to_grid(lat: float, lon: float, cell_m: float) -> Tuple[float, float]:
    """Return the centre of the grid cell containing the point.

    Rows are ``cell_m`` tall; columns are ``cell_m`` wide at the row's latitude. The
    grid depends only on ``cell_m``, never on the data.
    """
    dlat = cell_m / (KM_PER_DEG_LAT * 1000)
    lat_c = (math.floor(lat / dlat) + 0.5) * dlat
    lat_c = max(-90.0, min(90.0, lat_c))
    dlon = cell_m / (KM_PER_DEG_LAT * 1000 * max(math.cos(math.radians(lat_c)), 1e-6))
    lon_c = (math.floor(lon / dlon) + 0.5) * dlon
    return round(lat_c, 7), round(lon_c, 7)


def _as_number(value: Any) -> Optional[float]:
    """Interpret a JSON value as a finite number (numeric strings included)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def find_coordinate_pairs(obj: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Find (latitude key, longitude key) pairs in a dict.

    Matches ``latitude``/``longitude``, ``lat``/``lon``/``lng``/``long`` and prefixed
    variants such as ``startLatitude``/``startLongitude``, case-insensitively.
    """
    lowered = {key.lower(): key for key in obj if isinstance(key, str)}
    pairs = []
    for low, key in lowered.items():
        for suffix in LAT_SUFFIXES:
            if not low.endswith(suffix):
                continue
            prefix = low[: -len(suffix)]
            for lon_suffix in LON_SUFFIXES:
                partner = lowered.get(prefix + lon_suffix)
                if partner is not None:
                    pairs.append((key, partner))
                    break
            break
    return pairs


def _read_pair(obj: Dict[str, Any], lat_key: str, lon_key: str) -> Optional[Tuple[float, float]]:
    lat, lon = _as_number(obj.get(lat_key)), _as_number(obj.get(lon_key))
    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


def _write_pair(obj: Dict[str, Any], lat_key: str, lon_key: str, lat: float, lon: float) -> None:
    """Write coordinates back, keeping string-typed fields as strings."""
    obj[lat_key] = str(lat) if isinstance(obj[lat_key], str) else lat
    obj[lon_key] = str(lon) if isinstance(obj[lon_key], str) else lon


def iter_coordinates(node: Any) -> Iterator[Tuple[float, float]]:
    """Yield every recognised (lat, lon) in a JSON document."""
    if isinstance(node, dict):
        for lat_key, lon_key in find_coordinate_pairs(node):
            point = _read_pair(node, lat_key, lon_key)
            if point is not None:
                yield point
        for value in node.values():
            yield from iter_coordinates(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_coordinates(item)


@dataclass(frozen=True)
class Zone:
    """A privacy zone. ``place_*`` is the true location and must never be output."""

    place_lat: float
    place_lon: float
    center_lat: float
    center_lon: float
    radius_km: float

    def contains(self, lat: float, lon: float) -> bool:
        return haversine_km(lat, lon, self.center_lat, self.center_lon) <= self.radius_km


@dataclass
class Report:
    """What the anonymizer did, with no coordinates in it."""

    zones: int = 0
    radius_km: float = 0.0
    grid_m: float = 0.0
    zone_mode: str = "drop"
    sections: Dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    untouched_sections: List[str] = field(default_factory=list)
    dropped_keys: int = 0
    closest_remaining_m: Optional[float] = None

    def total(self, what: str) -> int:
        return sum(counter[what] for counter in self.sections.values())

    def lines(self) -> List[str]:
        out = [
            f"Protected places: {self.zones} "
            f"(zone radius {self.radius_km * 1000:.0f} m, centre displaced "
            f"{MIN_DISPLACEMENT * self.radius_km * 1000:.0f}-{MAX_DISPLACEMENT * self.radius_km * 1000:.0f} m)",
            f"Coordinates found: {self.total('found')}",
            f"  removed (inside a zone): {self.total('removed')}",
            f"  blanked (inside a zone, could not remove the record): {self.total('blanked')}",
            f"  moved to the zone centre: {self.total('to_zone_centre')}",
        ]
        if self.grid_m:
            out.append(f"  generalised to a {self.grid_m:.0f} m grid: {self.total('generalised')}")
        else:
            out.append("  grid generalisation: OFF (remaining coordinates are exact)")
        if self.dropped_keys:
            out.append(f"Fields removed with --drop-key: {self.dropped_keys}")
        out.append("By section:")
        for name, counter in self.sections.items():
            hidden = counter["removed"] + counter["blanked"] + counter["to_zone_centre"]
            out.append(f"  {name}: {counter['found']} found, {hidden} inside a zone")
        if self.untouched_sections:
            out.append(
                "Sections with no recognised coordinates (copied as they are - inspect before sharing): "
                + ", ".join(self.untouched_sections)
            )
        if self.closest_remaining_m is not None:
            out.append(
                f"Audit passed: closest remaining coordinate to a protected place is "
                f"{self.closest_remaining_m:.0f} m away (before grid generalisation)"
            )
        return out


class LocationAnonymizer:
    def __init__(
        self,
        home_primary_activity_id: str,
        anonymization_radius_km: float = 0.5,
        *,
        grid_m: float = 100.0,
        zone_mode: str = "drop",
        protect_activity_ids: Sequence[str] = (),
        drop_keys: Iterable[str] = (),
        key: Optional[bytes] = None,
        rng: Any = None,
    ):
        """
        Args:
            home_primary_activity_id: ``primaryActivityId`` of the home place(s).
            anonymization_radius_km: Radius of the privacy zone around each protected place.
            grid_m: Cell size for generalising the remaining coordinates; 0 disables it.
            zone_mode: ``drop`` removes records inside a zone; ``snap`` moves them to the
                (displaced) zone centre, keeping the record and its other fields.
            protect_activity_ids: Further ``primaryActivityId`` values to protect (e.g. work).
            drop_keys: Field names to delete wherever they appear.
            key: Secret that makes zone placement repeatable for the same place, so that
                anonymizing the same person's data twice does not produce two different
                zones that could be intersected.
            rng: Source of randomness when no key is given (default: the OS CSPRNG).
        """
        if not MIN_RADIUS_KM <= anonymization_radius_km <= MAX_RADIUS_KM:
            raise AnonymizationError(f"Radius must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM} km.")
        if grid_m != 0 and not MIN_GRID_M <= grid_m <= MAX_GRID_M:
            raise AnonymizationError(f"Grid size must be 0 (off) or between {MIN_GRID_M:.0f} and {MAX_GRID_M:.0f} m.")
        if zone_mode not in ZONE_MODES:
            raise AnonymizationError(f"Zone mode must be one of {ZONE_MODES}.")
        self.protected_ids = list(dict.fromkeys([home_primary_activity_id, *protect_activity_ids]))
        self.radius_km = anonymization_radius_km
        self.grid_m = grid_m
        self.zone_mode = zone_mode
        self.drop_keys = set(drop_keys)
        self.key = key
        self.rng = rng if rng is not None else secrets.SystemRandom()
        self.zones: List[Zone] = []
        self.report = Report()

    # -- zones -----------------------------------------------------------------

    def _uniform_pair(self, lat: float, lon: float) -> Tuple[float, float]:
        if self.key is None:
            return self.rng.random(), self.rng.random()
        digest = hmac.new(self.key, f"{lat:.3f},{lon:.3f}".encode(), hashlib.sha256).digest()
        return int.from_bytes(digest[:8], "big") / 2**64, int.from_bytes(digest[8:16], "big") / 2**64

    def _make_zone(self, lat: float, lon: float) -> Zone:
        u, v = self._uniform_pair(lat, lon)
        low, high = MIN_DISPLACEMENT * self.radius_km, MAX_DISPLACEMENT * self.radius_km
        distance = math.sqrt(low**2 + u * (high**2 - low**2))  # uniform over the ring's area
        bearing = 2 * math.pi * v
        center_lat = lat + distance * math.cos(bearing) / KM_PER_DEG_LAT
        center_lon = lon + distance * math.sin(bearing) / (
            KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6)
        )
        return Zone(lat, lon, center_lat, center_lon, self.radius_km)

    def _build_zones(self, data: Dict[str, Any]) -> List[Zone]:
        places = data.get("places")
        if not isinstance(places, list):
            raise AnonymizationError("Input has no 'places' list, so protected places cannot be identified.")
        zones: List[Zone] = []
        for activity_id in self.protected_ids:
            found = False
            for place in places:
                if not isinstance(place, dict) or place.get("primaryActivityId") != activity_id:
                    continue
                for lat_key, lon_key in find_coordinate_pairs(place):
                    point = _read_pair(place, lat_key, lon_key)
                    if point is None:
                        continue
                    found = True
                    # A second record for (almost) the same spot reuses the first zone:
                    # two independent zones around one place could be intersected.
                    if not any(
                        haversine_km(*point, z.place_lat, z.place_lon) <= 0.1 * self.radius_km for z in zones
                    ):
                        zones.append(self._make_zone(*point))
            if not found:
                raise AnonymizationError(
                    f"No place with primaryActivityId {activity_id!r} and valid coordinates was found."
                )
        return zones

    def _zone_for(self, lat: float, lon: float) -> Optional[Zone]:
        for zone in self.zones:
            if zone.contains(lat, lon):
                return zone
        return None

    # -- pass 1: remove everything inside a zone -------------------------------

    def _suppress_dict(self, obj: Dict[str, Any], section: str, in_list: bool) -> Any:
        for name in [k for k in obj if k in self.drop_keys]:
            del obj[name]
            self.report.dropped_keys += 1
        stats = self.report.sections[section]
        for lat_key, lon_key in find_coordinate_pairs(obj):
            point = _read_pair(obj, lat_key, lon_key)
            if point is None:
                continue
            stats["found"] += 1
            zone = self._zone_for(*point)
            if zone is None:
                continue
            if self.zone_mode == "snap":
                _write_pair(obj, lat_key, lon_key, zone.center_lat, zone.center_lon)
                stats["to_zone_centre"] += 1
            elif in_list and lat_key.lower() in LAT_SUFFIXES:
                stats["removed"] += 1
                return _DROP
            else:
                obj[lat_key] = obj[lon_key] = None
                stats["blanked"] += 1
        for name, value in obj.items():
            if isinstance(value, dict):
                self._suppress_dict(value, section, in_list=False)
            elif isinstance(value, list):
                obj[name] = self._suppress_list(value, section)
        return obj

    def _suppress_list(self, items: List[Any], section: str) -> List[Any]:
        kept = []
        for item in items:
            if isinstance(item, dict):
                if self._suppress_dict(item, section, in_list=True) is _DROP:
                    continue
            elif isinstance(item, list):
                item = self._suppress_list(item, section)
            kept.append(item)
        return kept

    # -- pass 2: audit ---------------------------------------------------------

    def _audit(self, node: Any, path: str = "$") -> None:
        """Fail if anything that looks like a protected place is still in the document.

        Recognised coordinate pairs are checked as pairs. Beyond that it deliberately
        ignores key names: any two other numbers in one object, or a short numeric
        array, that together land next to a protected place count as a leak.
        """
        clear_km = MIN_DISPLACEMENT * self.radius_km * 0.999
        if isinstance(node, dict):
            recognised = set()
            for lat_key, lon_key in find_coordinate_pairs(node):
                point = _read_pair(node, lat_key, lon_key)
                if point is None:
                    continue
                recognised.update((lat_key, lon_key))
                if any(haversine_km(*point, z.place_lat, z.place_lon) < clear_km for z in self.zones):
                    raise AnonymizationError(
                        f"Audit failed: {lat_key!r}/{lon_key!r} at {path} is still next to a protected place."
                    )
            # A recognised coordinate is not paired with unrelated numbers in the same
            # record (a longitude beside an accuracy value that happens to resemble the
            # home latitude would be a false alarm).
            numbers = [
                (k, n) for k, v in node.items() if k not in recognised and (n := _as_number(v)) is not None
            ]
            for zone in self.zones:
                dlat = clear_km / 110.5
                dlon = clear_km / (110.5 * max(math.cos(math.radians(zone.place_lat)), 1e-6))
                lat_like = [(k, n) for k, n in numbers if abs(n - zone.place_lat) <= dlat]
                lon_like = [(k, n) for k, n in numbers if abs(n - zone.place_lon) <= dlon]
                for lat_key, lat in lat_like:
                    for lon_key, lon in lon_like:
                        if lat_key != lon_key and haversine_km(lat, lon, zone.place_lat, zone.place_lon) < clear_km:
                            raise AnonymizationError(
                                f"Audit failed: fields {lat_key!r} and {lon_key!r} at {path} look like a "
                                f"protected location under unrecognised names. Remove them with --drop-key."
                            )
            for name, value in node.items():
                self._audit(value, f"{path}.{name}")
        elif isinstance(node, list):
            if 2 <= len(node) <= 3:
                first, second = _as_number(node[0]), _as_number(node[1])
                if first is not None and second is not None:
                    for zone in self.zones:
                        for lat, lon in ((first, second), (second, first)):
                            if abs(lat) <= 90 and haversine_km(lat, lon, zone.place_lat, zone.place_lon) < clear_km:
                                raise AnonymizationError(
                                    f"Audit failed: the array at {path} still holds a protected location. "
                                    f"Remove its parent field with --drop-key."
                                )
            for index, item in enumerate(node):
                self._audit(item, f"{path}[{index}]")

    # -- pass 3: generalise what is left ---------------------------------------

    def _generalise(self, node: Any, section: str) -> None:
        if isinstance(node, dict):
            for lat_key, lon_key in find_coordinate_pairs(node):
                point = _read_pair(node, lat_key, lon_key)
                if point is not None:
                    _write_pair(node, lat_key, lon_key, *snap_to_grid(*point, self.grid_m))
                    self.report.sections[section]["generalised"] += 1
            for value in node.values():
                self._generalise(value, section)
        elif isinstance(node, list):
            for item in node:
                self._generalise(item, section)

    # -- entry point -----------------------------------------------------------

    def anonymize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Return an anonymized copy of ``data``. Raises AnonymizationError if it cannot."""
        if not isinstance(data, dict):
            raise AnonymizationError("Input must be a JSON object.")
        self.zones = self._build_zones(data)
        self.report = Report(
            zones=len(self.zones), radius_km=self.radius_km, grid_m=self.grid_m, zone_mode=self.zone_mode
        )

        result = copy.deepcopy(data)
        for name in [k for k in result if k in self.drop_keys]:
            del result[name]
            self.report.dropped_keys += 1
        for name, value in result.items():
            if isinstance(value, dict):
                self._suppress_dict(value, name, in_list=False)
            elif isinstance(value, list):
                result[name] = self._suppress_list(value, name)
            if self.report.sections[name]["found"] == 0:
                del self.report.sections[name]
                if isinstance(value, (dict, list)):
                    self.report.untouched_sections.append(name)

        self._audit(result)
        distances = [
            haversine_km(lat, lon, z.place_lat, z.place_lon) for lat, lon in iter_coordinates(result) for z in self.zones
        ]
        self.report.closest_remaining_m = min(distances) * 1000 if distances else None

        if self.grid_m:
            for name, value in result.items():
                self._generalise(value, name)
        return result

    def create_visualization(self, original: Dict[str, Any], anonymized: Dict[str, Any], output_path: str) -> None:
        """Save a before/after plot. The plot shows ORIGINAL locations: do not share it."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        zone = self.zones[0]
        span_km = 3 * self.radius_km
        dlat = span_km / KM_PER_DEG_LAT
        dlon = span_km / (KM_PER_DEG_LAT * math.cos(math.radians(zone.place_lat)))
        angles = [2 * math.pi * i / 180 for i in range(181)]
        ring_lat = [zone.center_lat + self.radius_km * math.sin(a) / KM_PER_DEG_LAT for a in angles]
        ring_lon = [zone.center_lon + self.radius_km * math.cos(a) * dlon / span_km for a in angles]

        fig, axes = plt.subplots(1, 2, figsize=(16, 8))
        panels = (
            (axes[0], list(iter_coordinates(original)), "tab:blue", "Original (private)"),
            (axes[1], list(iter_coordinates(anonymized)), "tab:green", "Anonymized output"),
        )
        for ax, points, colour, title in panels:
            if points:
                lats, lons = zip(*points)
                ax.scatter(lons, lats, c=colour, alpha=0.6, s=14, label="Location points")
            ax.plot(ring_lon, ring_lat, color="orange", linestyle="--", linewidth=2, label="Privacy zone")
            ax.set_xlim(zone.place_lon - dlon, zone.place_lon + dlon)
            ax.set_ylim(zone.place_lat - dlat, zone.place_lat + dlat)
            ax.set_aspect(1 / math.cos(math.radians(zone.place_lat)))
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_title(title)
            ax.grid(True, alpha=0.3)
        axes[0].scatter(
            [zone.place_lon], [zone.place_lat], c="red", s=200, marker="*", edgecolors="black", label="Protected place"
        )
        for ax in axes:
            ax.legend(loc="upper right")
        fig.suptitle(
            "CONTAINS ORIGINAL LOCATIONS - FOR YOUR OWN CHECKING ONLY - DO NOT SHARE",
            color="red",
            fontweight="bold",
        )
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)


def _load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise AnonymizationError(f"Input file '{path}' not found.") from None
    except json.JSONDecodeError as exc:
        raise AnonymizationError(f"Invalid JSON in input file: {exc}") from None
    except OSError as exc:
        raise AnonymizationError(f"Could not read input file: {exc}") from None


def _write_json_atomically(data: Any, path: str) -> None:
    """Write via a temporary file so a failure never leaves a partial output behind."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    except OSError as exc:
        raise AnonymizationError(f"Could not write to output location: {exc}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError as exc:
        raise AnonymizationError(f"Could not write output file: {exc}") from None
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _read_key(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            key = handle.read().strip()
    except OSError as exc:
        raise AnonymizationError(f"Could not read key file: {exc}") from None
    if len(key) < 16:
        raise AnonymizationError("Key file must contain at least 16 bytes.")
    return key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Anonymize a JSON location export by removing data around protected places "
        "and generalising the rest. Writes nothing if it cannot do so safely."
    )
    parser.add_argument("input_file", help="Input JSON file path")
    parser.add_argument("output_file", help="Output JSON file path")
    parser.add_argument("home_activity_id", help="primaryActivityId that identifies the home place")
    parser.add_argument(
        "--radius", type=float, default=0.5,
        help=f"Privacy zone radius in km, {MIN_RADIUS_KM}-{MAX_RADIUS_KM} (default: 0.5)",
    )
    parser.add_argument(
        "--grid", type=float, default=100.0, metavar="METRES",
        help=f"Grid cell size for remaining coordinates, {MIN_GRID_M:.0f}-{MAX_GRID_M:.0f}; 0 turns it off (default: 100)",
    )
    parser.add_argument(
        "--protect", action="append", default=[], metavar="ACTIVITY_ID",
        help="Another primaryActivityId to protect like home, e.g. work (repeatable)",
    )
    parser.add_argument(
        "--zone-mode", choices=ZONE_MODES, default="drop",
        help="drop: remove records inside a zone (default). snap: keep them, moved to the displaced zone centre",
    )
    parser.add_argument(
        "--drop-key", action="append", default=[], metavar="NAME",
        help="Delete this field wherever it appears, e.g. predictions or address (repeatable)",
    )
    parser.add_argument(
        "--key-file", metavar="PATH",
        help="Secret key file; makes zone placement repeatable so re-anonymizing the same person is safe",
    )
    parser.add_argument(
        "--viz", metavar="PATH",
        help="Save a before/after image for your own checking. It shows original locations: never share it",
    )
    parser.add_argument("--noise", type=float, help=argparse.SUPPRESS)  # removed; accepted so old commands fail soft
    parser.add_argument("--no-viz", action="store_true", help=argparse.SUPPRESS)  # now the default
    return parser


def run(args: argparse.Namespace) -> None:
    if os.path.abspath(args.input_file) == os.path.abspath(args.output_file):
        raise AnonymizationError("Output file must be different from the input file.")
    if args.noise is not None:
        print("Note: --noise is no longer used and is ignored (see README).", file=sys.stderr)

    anonymizer = LocationAnonymizer(
        home_primary_activity_id=args.home_activity_id,
        anonymization_radius_km=args.radius,
        grid_m=args.grid,
        zone_mode=args.zone_mode,
        protect_activity_ids=args.protect,
        drop_keys=args.drop_key,
        key=_read_key(args.key_file) if args.key_file else None,
    )
    data = _load_json(args.input_file)
    anonymized = anonymizer.anonymize_data(data)
    _write_json_atomically(anonymized, args.output_file)

    print("\n".join(anonymizer.report.lines()))
    print(f"Anonymized data saved to {args.output_file}")

    if args.viz:
        try:
            anonymizer.create_visualization(data, anonymized, args.viz)
        except ImportError:
            raise AnonymizationError(
                "The anonymized file was written, but --viz needs matplotlib: pip install matplotlib"
            ) from None
        print(f"Visualization saved to {args.viz} (contains original locations - do not share)")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except AnonymizationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if not os.path.exists(args.output_file):
            print("No output file was written.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

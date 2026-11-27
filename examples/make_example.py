"""Write a synthetic location export for trying the anonymizer.

    python examples/make_example.py example_input.json
    python location_anonymizer.py example_input.json example_output.json HOME --protect WORK

The coordinates are invented: a "home", a "work" 5 km away, and commutes between them.
"""

import json
import math
import random
import sys

HOME = (40.0, 20.0)
WORK = (40.03, 20.04)


def jitter(point, metres, rng):
    lat, lon = point
    return (
        lat + rng.gauss(0, metres) / 111_320,
        lon + rng.gauss(0, metres) / (111_320 * math.cos(math.radians(lat))),
    )


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "example_input.json"
    rng = random.Random(0)
    points = [jitter(HOME, 8, rng) for _ in range(300)] + [jitter(WORK, 8, rng) for _ in range(200)]
    for _ in range(4):
        for i in range(60):
            t = i / 59
            points.append(jitter((HOME[0] + t * (WORK[0] - HOME[0]), HOME[1] + t * (WORK[1] - HOME[1])), 8, rng))
    data = {
        "locations": [
            {"latitude": lat, "longitude": lon, "timestamp": 1_700_000_000 + 60 * i}
            for i, (lat, lon) in enumerate(points)
        ],
        "places": [
            {"primaryActivityId": "HOME", "latitude": HOME[0], "longitude": HOME[1]},
            {"primaryActivityId": "WORK", "latitude": WORK[0], "longitude": WORK[1]},
        ],
        "geoFence": [{"latitude": HOME[0], "longitude": HOME[1], "radius": 100, "event": "enter"}],
        "userMobilities": [],
        "predictions": [],
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    print(f"Wrote {len(points)} synthetic points to {out_path}")


if __name__ == "__main__":
    main()

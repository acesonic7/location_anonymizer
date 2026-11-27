import copy
import json
import math
import random

import pytest

import location_anonymizer as la

# Entirely synthetic: no real person lives or works at these points.
HOME = (40.0, 20.0)
WORK = (40.03, 20.04)
RADIUS_KM = 0.5


def jitter(point, metres, rng):
    lat, lon = point
    return (
        lat + rng.gauss(0, metres) / 111_320,
        lon + rng.gauss(0, metres) / (111_320 * math.cos(math.radians(lat))),
    )


def make_data(seed=1):
    rng = random.Random(seed)
    points = [jitter(HOME, 8, rng) for _ in range(300)] + [jitter(WORK, 8, rng) for _ in range(200)]
    for i in range(200):
        t = i / 199
        on_route = (HOME[0] + t * (WORK[0] - HOME[0]), HOME[1] + t * (WORK[1] - HOME[1]))
        points.append(jitter(on_route, 8, rng))
    return {
        "locations": [{"latitude": lat, "longitude": lon, "timestamp": i} for i, (lat, lon) in enumerate(points)],
        "places": [
            {"primaryActivityId": "HOME", "latitude": HOME[0], "longitude": HOME[1], "address": "1 Example St"},
            {"primaryActivityId": "WORK", "latitude": WORK[0], "longitude": WORK[1]},
        ],
        "geoFence": [{"latitude": HOME[0], "longitude": HOME[1], "radius": 100, "event": "enter"}],
        "userMobilities": [
            {
                "mode": "bus",
                "startLatitude": HOME[0],
                "startLongitude": HOME[1],
                "endLatitude": WORK[0],
                "endLongitude": WORK[1],
            }
        ],
        "predictions": [{"location": {"lat": HOME[0], "lng": HOME[1]}, "score": 0.9}],
    }


def anonymizer(**kwargs):
    kwargs.setdefault("rng", random.Random(42))
    return la.LocationAnonymizer("HOME", RADIUS_KM, **kwargs)


def metres_from(place, point):
    return la.haversine_km(*point, *place) * 1000


def write_input(tmp_path, data):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(data))
    return path


# -- the privacy property --------------------------------------------------------


def test_nothing_remains_near_home_in_any_section():
    out = anonymizer().anonymize_data(make_data())
    remaining = list(la.iter_coordinates(out))
    assert remaining, "data away from home should survive"
    # Home is at least 0.4 * radius inside the zone; snapping moves a point by at most ~71 m.
    floor_m = (1 - la.MAX_DISPLACEMENT) * RADIUS_KM * 1000 - 100 * math.sqrt(2) / 2
    assert min(metres_from(HOME, p) for p in remaining) >= floor_m


def test_home_coordinates_are_not_in_the_output_text():
    out = anonymizer().anonymize_data(make_data())
    text = json.dumps(out)
    assert "1 Example St" not in text  # the home place record is gone, address and all
    assert not any(p.get("primaryActivityId") == "HOME" for p in out["places"])
    assert out["geoFence"] == []
    assert out["userMobilities"][0]["startLatitude"] is None
    assert out["userMobilities"][0]["startLongitude"] is None
    assert out["predictions"][0]["location"] == {"lat": None, "lng": None}


def test_zone_centre_is_displaced_but_keeps_home_inside():
    for seed in range(200):
        a = anonymizer(rng=random.Random(seed))
        a.anonymize_data(make_data())
        (zone,) = a.zones
        offset_km = la.haversine_km(zone.center_lat, zone.center_lon, *HOME)
        assert la.MIN_DISPLACEMENT * RADIUS_KM * 0.99 <= offset_km <= la.MAX_DISPLACEMENT * RADIUS_KM * 1.01


def test_centre_of_the_removed_area_does_not_give_home_away():
    data = make_data()
    a = anonymizer(grid_m=0)
    out = a.anonymize_data(data)
    kept = {(l["latitude"], l["longitude"]) for l in out["locations"]}
    removed = [(l["latitude"], l["longitude"]) for l in data["locations"] if (l["latitude"], l["longitude"]) not in kept]
    # Every removed point is inside the zone, which is all an observer can learn.
    assert all(a.zones[0].contains(*p) for p in removed)
    assert len(removed) >= 300


def test_work_is_untouched_unless_protected():
    out = anonymizer().anonymize_data(make_data())
    assert min(metres_from(WORK, p) for p in la.iter_coordinates(out)) < 100

    out = anonymizer(protect_activity_ids=["WORK"]).anonymize_data(make_data())
    assert min(metres_from(WORK, p) for p in la.iter_coordinates(out)) >= 100


def test_snap_mode_keeps_records_at_the_displaced_centre():
    a = anonymizer(zone_mode="snap", grid_m=0, drop_keys=["address"])
    out = a.anonymize_data(make_data())
    assert len(out["locations"]) == len(make_data()["locations"])
    home_place = next(p for p in out["places"] if p["primaryActivityId"] == "HOME")
    centre = (home_place["latitude"], home_place["longitude"])
    assert centre == (a.zones[0].center_lat, a.zones[0].center_lon)
    assert metres_from(HOME, centre) >= la.MIN_DISPLACEMENT * RADIUS_KM * 1000 * 0.99
    assert "address" not in home_place
    assert min(metres_from(HOME, p) for p in la.iter_coordinates(out)) >= la.MIN_DISPLACEMENT * RADIUS_KM * 1000 * 0.99


# -- the audit ---------------------------------------------------------------------


def test_audit_catches_home_under_unrecognised_field_names():
    data = make_data()
    data["profile"] = {"hx": HOME[0], "hy": HOME[1]}
    with pytest.raises(la.AnonymizationError, match="Audit failed"):
        anonymizer().anonymize_data(data)
    out = anonymizer(drop_keys=["profile"]).anonymize_data(data)
    assert "profile" not in out


def test_audit_catches_geojson_style_arrays():
    data = make_data()
    data["shapes"] = [{"geometry": {"type": "Point", "coordinates": [HOME[1], HOME[0]]}}]
    with pytest.raises(la.AnonymizationError, match="Audit failed"):
        anonymizer().anonymize_data(data)


def test_audit_does_not_pair_a_coordinate_with_an_unrelated_number():
    # "accuracy" equals the home latitude and the record sits due north of home, so
    # (accuracy, longitude) would read as the home if the audit paired them up.
    data = make_data()
    data["locations"] = [{"latitude": HOME[0] + 0.02, "longitude": HOME[1], "accuracy": HOME[0]}]
    out = anonymizer(grid_m=0).anonymize_data(data)
    assert len(out["locations"]) == 1


def test_audit_message_does_not_contain_the_coordinates():
    data = make_data()
    data["profile"] = {"hx": HOME[0] + 0.0001234, "hy": HOME[1] + 0.0001234}
    with pytest.raises(la.AnonymizationError) as excinfo:
        anonymizer().anonymize_data(data)
    assert "40.0001" not in str(excinfo.value) and "20.0001" not in str(excinfo.value)


# -- failing closed ----------------------------------------------------------------


def test_unknown_home_id_raises():
    with pytest.raises(la.AnonymizationError):
        la.LocationAnonymizer("NOPE").anonymize_data(make_data())


def test_unknown_extra_protected_id_raises():
    with pytest.raises(la.AnonymizationError):
        anonymizer(protect_activity_ids=["NOPE"]).anonymize_data(make_data())


def test_home_place_without_coordinates_raises():
    data = make_data()
    data["places"][0]["latitude"] = None
    with pytest.raises(la.AnonymizationError):
        anonymizer().anonymize_data(data)


def test_cli_writes_nothing_when_home_is_not_found(tmp_path, capsys):
    out_path = tmp_path / "out.json"
    code = la.main([str(write_input(tmp_path, make_data())), str(out_path), "NOPE"])
    assert code != 0
    assert not out_path.exists()
    assert list(tmp_path.iterdir()) == [tmp_path / "in.json"]  # no temp file left behind
    assert "No output file was written" in capsys.readouterr().err


def test_cli_refuses_to_overwrite_the_input(tmp_path):
    data = make_data()
    in_path = write_input(tmp_path, data)
    assert la.main([str(in_path), str(in_path), "HOME"]) != 0
    assert json.loads(in_path.read_text()) == data


def test_cli_rejects_bad_json(tmp_path):
    in_path = tmp_path / "in.json"
    in_path.write_text("{not json")
    assert la.main([str(in_path), str(tmp_path / "out.json"), "HOME"]) != 0
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("flag,value", [("--radius", "0.01"), ("--radius", "50"), ("--grid", "3")])
def test_cli_rejects_out_of_range_settings(tmp_path, flag, value):
    out_path = tmp_path / "out.json"
    assert la.main([str(write_input(tmp_path, make_data())), str(out_path), "HOME", flag, value]) != 0
    assert not out_path.exists()


# -- normal operation ----------------------------------------------------------------


def test_cli_success_and_console_output_has_no_home_coordinates(tmp_path, capsys):
    out_path = tmp_path / "out.json"
    code = la.main([str(write_input(tmp_path, make_data())), str(out_path), "HOME", "--no-viz"])
    assert code == 0
    out = json.loads(out_path.read_text())
    assert out["locations"]
    printed = capsys.readouterr()
    assert "40.0" not in printed.out + printed.err
    assert "Audit passed" in printed.out
    assert list(tmp_path.glob("*.png")) == []  # no image unless asked for


def test_input_is_not_modified():
    data = make_data()
    before = copy.deepcopy(data)
    anonymizer().anonymize_data(data)
    assert data == before


def test_remaining_points_sit_on_the_grid():
    data = make_data()
    out = anonymizer(grid_m=100).anonymize_data(data)
    for lat, lon in la.iter_coordinates(out):
        assert la.snap_to_grid(lat, lon, 100) == pytest.approx((lat, lon), abs=1e-6)
    exact = anonymizer(grid_m=0).anonymize_data(data)
    originals = {(l["latitude"], l["longitude"]) for l in data["locations"]}
    assert all((l["latitude"], l["longitude"]) in originals for l in exact["locations"])


def test_grid_moves_points_by_at_most_half_a_cell_diagonal():
    rng = random.Random(3)
    for _ in range(500):
        point = (rng.uniform(-70, 70), rng.uniform(-179, 179))
        assert metres_from(point, la.snap_to_grid(*point, 100)) <= 100 * math.sqrt(2) / 2 + 1


def test_key_makes_zone_placement_repeatable():
    def centre(key):
        a = la.LocationAnonymizer("HOME", RADIUS_KM, key=key)
        a.anonymize_data(make_data())
        return a.zones[0].center_lat, a.zones[0].center_lon

    assert centre(b"k" * 32) == centre(b"k" * 32)
    assert centre(b"k" * 32) != centre(b"j" * 32)


def test_duplicate_home_records_share_one_zone():
    data = make_data()
    data["places"].append({"primaryActivityId": "HOME", "latitude": HOME[0] + 0.00001, "longitude": HOME[1]})
    a = anonymizer()
    a.anonymize_data(data)
    assert len(a.zones) == 1


def test_string_coordinates_are_handled_and_stay_strings():
    data = make_data()
    data["locations"] = [
        {"latitude": str(HOME[0]), "longitude": str(HOME[1])},
        {"latitude": str(WORK[0]), "longitude": str(WORK[1])},
    ]
    out = anonymizer().anonymize_data(data)
    assert len(out["locations"]) == 1
    assert isinstance(out["locations"][0]["latitude"], str)


def test_find_coordinate_pairs():
    pairs = la.find_coordinate_pairs
    assert pairs({"latitude": 1, "longitude": 2}) == [("latitude", "longitude")]
    assert pairs({"Lat": 1, "Lng": 2}) == [("Lat", "Lng")]
    assert pairs({"startLat": 1, "startLon": 2, "endLat": 3}) == [("startLat", "startLon")]
    assert pairs({"flat": 1, "longitude": 2}) == []


def test_visualization_is_written_only_on_request(tmp_path):
    pytest.importorskip("matplotlib")
    out_path, image = tmp_path / "out.json", tmp_path / "check.png"
    code = la.main([str(write_input(tmp_path, make_data())), str(out_path), "HOME", "--viz", str(image)])
    assert code == 0
    assert image.stat().st_size > 0

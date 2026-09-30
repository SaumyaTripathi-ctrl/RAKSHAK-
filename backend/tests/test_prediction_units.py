"""Routing, weather, facilities, reroute ranking and explanations (no models needed)."""

from __future__ import annotations

import httpx
import pytest
from rakshak.prediction.explain import drivers
from rakshak.prediction.facilities import Facility, compatible, haversine_km, load_facilities
from rakshak.prediction.reroute import recommend
from rakshak.prediction.routing import Router
from rakshak.prediction.weather import WeatherClient
from rakshak_ml.bands import get_band

PUNE = (18.5204, 73.8567)
MUMBAI = (19.0760, 72.8777)


def test_haversine_known_distances():
    assert haversine_km(*PUNE, *MUMBAI) == pytest.approx(120, abs=6)  # ~120 km straight line
    assert haversine_km(*PUNE, *PUNE) == 0


# ------------------------------------------------------------------ routing


def osrm_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": "Ok",
            "routes": [
                {
                    "distance": 150_000.0,
                    "duration": 7200.0,
                    "geometry": {
                        "coordinates": [[73.8567, 18.5204], [73.3, 18.8], [72.8777, 19.076]]
                    },
                }
            ],
        },
    )


async def test_osrm_success_parses_and_caches():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return osrm_ok(req)

    r = Router(transport=httpx.MockTransport(handler))
    a = await r.route(PUNE, MUMBAI)
    assert (a.distance_km, a.duration_min, a.source, a.status) == (
        150.0,
        120.0,
        "osrm",
        "road_route",
    )
    assert a.geometry[0] == [18.5204, 73.8567] and a.geometry[-1] == [
        19.076,
        72.8777,
    ]  # lat, lon order
    assert "73.856700,18.520400;72.877700,19.076000" in calls[0]  # OSRM wants lon,lat
    b = await r.route((PUNE[0] + 0.0001, PUNE[1]), MUMBAI)  # same 3-decimal cell -> cached
    assert b is a and len(calls) == 1


async def test_osrm_failure_falls_back_labelled_and_backs_off():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    r = Router(transport=httpx.MockTransport(handler), backoff_s=60)
    a = await r.route(PUNE, MUMBAI)
    assert a.source == "haversine" and a.status == "estimated" and "straight-line" in a.note
    assert a.distance_km == pytest.approx(haversine_km(*PUNE, *MUMBAI), abs=0.1)
    assert a.duration_min == pytest.approx(a.distance_km / 30 * 60, abs=0.2)
    await r.route(PUNE, (18.0, 73.0))  # circuit breaker: no second network attempt while backed off
    assert len(calls) == 1


async def test_osrm_bad_payload_and_disabled():
    r = Router(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"code": "NoRoute"}))
    )
    assert (await r.route(PUNE, MUMBAI)).source == "haversine"
    off = Router(enabled=False)
    assert (await off.route(PUNE, MUMBAI)).source == "haversine" and off.osrm_calls == 0


async def test_geometry_is_downsampled():
    pts = [[73.0 + i * 0.001, 18.0 + i * 0.001] for i in range(1000)]

    def handler(req):
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [{"distance": 1, "duration": 1, "geometry": {"coordinates": pts}}],
            },
        )

    r = Router(transport=httpx.MockTransport(handler))
    assert len((await r.route(PUNE, MUMBAI)).geometry) == 200


# ------------------------------------------------------------------ weather


async def test_weather_disabled_returns_defaults_without_network():
    w = WeatherClient(
        enabled=False, transport=httpx.MockTransport(lambda r: pytest.fail("no network expected"))
    )
    assert (await w.get(18, 73)).source == "default"
    assert w.peek(18, 73).source == "default"


async def test_weather_fetch_cache_and_failure():
    calls = []

    def handler(req):
        calls.append(req.url.params["latitude"])
        return httpx.Response(
            200,
            json={
                "current": {"wind_speed_10m": 12.5},
                "hourly": {"precipitation_probability": [40]},
            },
        )

    w = WeatherClient(enabled=True, transport=httpx.MockTransport(handler))
    got = await w.get(18.52, 73.81)
    assert (got.rain_probability, got.wind_speed, got.source) == (0.4, 12.5, "open-meteo")
    await w.get(18.53, 73.84)  # same 0.1 degree cell
    assert len(calls) == 1
    bad = WeatherClient(enabled=True, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert (await bad.get(18, 73)).source == "default"


async def test_weather_peek_refreshes_in_background():
    w = WeatherClient(
        enabled=True,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "current": {"wind_speed_10m": 5},
                    "hourly": {"precipitation_probability": [10]},
                },
            )
        ),
    )
    assert w.peek(18.5, 73.8).source == "default"  # immediate, non-blocking
    import asyncio

    await asyncio.gather(*w._tasks)
    assert w.peek(18.5, 73.8).source == "open-meteo"


# ------------------------------------------------------------------ facilities / reroute


def fac(id_, lat, lng, smin=10, smax=14, free=100.0, active=True, name=None):
    return Facility(
        id_,
        name or id_,
        "cold_storage",
        "MH",
        "X",
        lat,
        lng,
        smin,
        smax,
        free * 2,
        free,
        active,
        "synthetic",
    )


def test_shipped_dataset_is_labelled_synthetic():
    fs = load_facilities()
    assert len(fs) > 100 and {f.data_source for f in fs} == {"synthetic"}
    assert all("(SYNTHETIC)" in f.name for f in fs)
    assert {f.type for f in fs} == {"cold_storage", "fpo_packhouse", "ripening_chamber"}


def test_compatibility_rules():
    mango = get_band("mango")  # 10-13
    milk = get_band("milk")  # 2-4
    assert compatible(fac("a", 0, 0, 10, 14), mango)
    assert compatible(fac("b", 0, 0, 2, 14), mango) and compatible(fac("b", 0, 0, 2, 14), milk)
    assert not compatible(fac("c", 0, 0, 0, 4), mango)  # too cold for mango
    assert not compatible(fac("d", 0, 0, 10, 14), milk)  # too warm for milk
    assert not compatible(fac("e", 0, 0, 10, 14, active=False), mango)
    assert not compatible(
        fac("f", 0, 0, 10, 14, free=0.5), mango, weight_kg=2000
    )  # not enough room


async def test_recommend_picks_fastest_compatible_and_flags_unreachable():
    mango = get_band("mango")
    fs = [
        fac("near-bad", 18.53, 73.86, 0, 4),  # closest but incompatible
        fac("mid", 18.70, 73.90),
        fac("far", 19.50, 74.50),
    ]
    router = Router(enabled=False)  # deterministic Haversine
    rec = await recommend(router, fs, mango, PUNE, rsl_hours=10)
    assert rec.recommended.facility.id == "mid" and [a.facility.id for a in rec.alternatives] == [
        "far"
    ]
    assert rec.recommended.reachable_before_spoilage is True and "compatible" in rec.reason
    tight = await recommend(router, fs, mango, PUNE, rsl_hours=0.2)
    assert (
        tight.recommended.reachable_before_spoilage is False
        and "exceeds the remaining safe life" in tight.reason
    )
    none = await recommend(router, [fs[0]], mango, PUNE)
    assert none.recommended is None and "no active compatible" in none.reason


async def test_recommend_prefers_reachable_over_nearer_unreachable():
    mango = get_band("mango")

    # 'quick' is reachable in time; make 'slow' nearer by straight line but slower by road.
    class StubRouter(Router):
        async def route(self, a, b):
            from rakshak.prediction.routing import Route

            slow = b[0] < 18.6
            return Route(10 if slow else 30, 300 if slow else 30, "osrm", "road_route")

    fs = [fac("slow", 18.55, 73.86), fac("quick", 18.80, 73.90)]
    rec = await recommend(StubRouter(enabled=False), fs, mango, PUNE, rsl_hours=2)
    assert rec.recommended.facility.id == "quick"


def feats(**kw):
    base = dict(
        temperature=12.0, temperature_deviation=0.0, time_outside_temp_range=0.0, ethylene_index=5.0,
        ethylene_rate_of_change=0.0, max_shock=0.0, shock_count=0.0, humidity=88.0, humidity_deviation=0.0,
        scrubber_on=0.0, flap_position=0.0,
    )  # fmt: skip
    base.update(kw)
    return base


def test_drivers_rank_by_severity_and_cite_numbers():
    band = get_band("mango")
    d = drivers(
        feats(temperature=17.0, temperature_deviation=4.0, time_outside_temp_range=300, ethylene_index=75,
              ethylene_rate_of_change=0.3, max_shock=2.4, shock_count=3, flap_position=100, scrubber_on=1),
        band,
    )  # fmt: skip
    assert len(d) == 4 and d[0]["severity"] == 3
    text = " | ".join(x["text"] for x in d)
    assert (
        "4.0 °C above the 13 °C limit" in text and "5.0 h" in text and "Ethylene index 75%" in text
    )
    assert drivers(feats(), band) == []


def test_drivers_ignore_ethylene_for_milk_and_humidity_band_for_milk():
    milk = get_band("milk")
    out = drivers(feats(ethylene_index=90, humidity=10, humidity_deviation=40), milk)
    assert all(x["factor"] not in ("ethylene", "humidity") for x in out)

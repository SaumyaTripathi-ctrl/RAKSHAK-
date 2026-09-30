"""Human-readable reasons behind a risk value (rule-based, derived from the feature vector)."""

from __future__ import annotations

from rakshak_ml.bands import FoodBand


def drivers(f: dict[str, float], band: FoodBand, limit: int = 4) -> list[dict]:
    """Most relevant factors first. Each: {"factor", "severity" (0-3), "text"}."""
    out: list[tuple[int, str, str]] = []
    t, dev = f["temperature"], f["temperature_deviation"]
    if dev > 0:
        side = "above" if t > band.max_temp else "below"
        limit_c = band.max_temp if t > band.max_temp else band.min_temp
        sev = 3 if dev >= 3 else 2 if dev >= 1.5 else 1
        out.append(
            (
                sev,
                "temperature",
                f"Temperature {t:.1f} °C is {dev:.1f} °C {side} the {limit_c:g} °C limit",
            )
        )
    mins = f["time_outside_temp_range"]
    if mins >= 15:
        hours = mins / 60
        txt = f"{hours:.1f} h" if hours >= 1 else f"{mins:.0f} min"
        out.append(
            (
                3 if mins >= 240 else 2 if mins >= 60 else 1,
                "exposure",
                f"{txt} spent outside the safe temperature band so far",
            )
        )
    if band.ethylene_sensitive or band.ethylene_producer:
        idx, rate = f["ethylene_index"], f["ethylene_rate_of_change"]
        if idx >= 30 or rate > 0.12:
            rising = f", rising {rate * 60:.0f} pts/h" if rate > 0.12 else ""
            out.append(
                (
                    3 if idx >= 70 else 2 if idx >= 40 else 1,
                    "ethylene",
                    f"Ethylene index {idx:.0f}%{rising}",
                )
            )
    if f["max_shock"] >= 1.0:
        out.append(
            (
                2 if f["max_shock"] >= 2.0 else 1,
                "shock",
                f"Strong shock up to {f['max_shock']:.1f} g ({f['shock_count']:.0f} events)",
            )
        )
    hdev = f["humidity_deviation"]
    if hdev >= 5 and band.max_rh - band.min_rh < 50:
        out.append(
            (
                1,
                "humidity",
                f"Humidity {f['humidity']:.0f}% is {hdev:.0f} points outside the {band.min_rh:g}-{band.max_rh:g}% band",
            )
        )
    if f["scrubber_on"]:
        out.append((0, "scrubber", "Ethylene scrubber fan is running"))
    if f["flap_position"] > 0:
        out.append((0, "flap", f"PCM cooling flap open {f['flap_position']:.0f}%"))
    out.sort(key=lambda x: -x[0])
    return [{"factor": k, "severity": s, "text": txt} for s, k, txt in out[:limit]]

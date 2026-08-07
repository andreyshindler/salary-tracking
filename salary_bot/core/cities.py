"""Israeli cities offered for Shabbat/holiday times.

Candle-lighting offsets differ by local custom: Jerusalem lights 40 minutes
before sunset, Haifa 30, most other places 18-20. That difference is real money
when the 150% rest-day rate starts at candle lighting, so it is per-city here
rather than a single global default.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    key: str
    name_he: str
    latitude: float
    longitude: float
    candle_offset_minutes: int


CITIES: dict[str, City] = {
    c.key: c
    for c in [
        City("jerusalem", "ירושלים", 31.7683, 35.2137, 40),
        City("tel_aviv", "תל אביב", 32.0853, 34.7818, 18),
        City("haifa", "חיפה", 32.7940, 34.9896, 30),
        City("beer_sheva", "באר שבע", 31.2530, 34.7915, 18),
        City("netanya", "נתניה", 32.3215, 34.8532, 18),
        City("ashdod", "אשדוד", 31.8014, 34.6435, 18),
        City("rishon", "ראשון לציון", 31.9730, 34.8066, 18),
        City("petah_tikva", "פתח תקווה", 32.0878, 34.8878, 18),
        City("eilat", "אילת", 29.5577, 34.9519, 18),
        City("tiberias", "טבריה", 32.7922, 35.5312, 18),
        City("safed", "צפת", 32.9646, 35.4960, 18),
    ]
}


def get_city(key: str) -> City:
    return CITIES.get(key, CITIES["tel_aviv"])

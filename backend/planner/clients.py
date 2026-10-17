# all the calls to outside apis are here (routing, geocoding, weather)
# all free. only tomtom needs a key (TOMTOM_API_KEY env var)

import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from django.core.cache import cache
from opentelemetry import context as otel_context
from opentelemetry import trace

# travelMode=truck uses truck speeds + road restrictions (weight limits etc)
TOMTOM_URL = "https://api.tomtom.com/routing/1/calculateRoute/"
TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY", "")
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://photon.komoot.io/api/"

# photon returns 403 for the default python-requests user agent, took a while to figure out
HEADERS = {"User-Agent": "truck-weather-router (interview assignment)"}

# cache api results for a while. same trip clicked twice (or the demo) doesn't hit the apis
# again, and keeps us under open meteo's hourly limit. django's default cache = in memory
CACHE_SECONDS = 30 * 60

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def in_parallel(fn, items, workers=8):
    # run fn for each item in threads. passes the tracing context into the threads,
    # otherwise their spans don't show up under the request in jaeger
    ctx = otel_context.get_current()

    def run(item):
        token = otel_context.attach(ctx)
        try:
            return fn(item)
        finally:
            otel_context.detach(token)

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(run, items))


def search_places(text):
    # towns/cities in the US or india matching the text, best photon match first.
    # used for the suggestions dropdown and for typed text in the plan
    with tracer.start_as_current_span("search_places") as span:
        span.set_attribute("text", text)
        key = "places:" + text.lower().strip().replace(" ", "_")
        cached = cache.get(key)
        span.set_attribute("cache_hit", cached is not None)
        if cached is not None:
            return cached
        res = requests.get(GEOCODE_URL, params={
            "q": text,
            "limit": 15,
            # only places (city, town, village..), otherwise "Banglore" gave a bakery
            "osm_tag": "place",
        }, headers=HEADERS, timeout=10)
        res.raise_for_status()
        places = []
        for f in res.json()["features"]:
            p = f["properties"]
            # spotter is a US trucking company, and I'm applying from india. other countries
            # are dropped, that's what sent typos to belgium ("Chenai") or kenya ("Mumbay")
            if p.get("countrycode") not in ("US", "IN"):
                continue
            name = p.get("name", text)
            if p.get("state"):
                name = name + ", " + p["state"]
            places.append({
                "name": name,
                "lat": f["geometry"]["coordinates"][1],
                "lon": f["geometry"]["coordinates"][0],
                "type": p.get("osm_value", ""),
            })
        cache.set(key, places, 24 * 3600)  # places don't move
        return places


def get_routes(points, weight_lb, depart, alternatives=True):
    # returns list of {coords: [[lat, lon]], segment_secs: [...], distance_m, duration_s}
    with tracer.start_as_current_span("tomtom_route") as span:
        span.set_attribute("waypoints", len(points))
        span.set_attribute("alternatives", alternatives)
        routes = _get_routes(points, weight_lb, depart, alternatives, span)
        span.set_attribute("routes_returned", len(routes))
        return routes


def _get_routes(points, weight_lb, depart, alternatives, span):
    coord_str = ":".join([str(p[0]) + "," + str(p[1]) for p in points])
    params = {
        "key": TOMTOM_API_KEY,
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "vehicleWeight": round(weight_lb * 0.4536),  # tomtom wants kg
        "traffic": "true",
        "instructionsType": "coded",  # need the instructions for the timing below
        # departAt has to be in the future, we allow a bit in the past so use now then
        "departAt": depart.isoformat() if depart > datetime.now(timezone.utc) else "now",
    }
    if alternatives:
        params["maxAlternatives"] = 2  # 1 main + 2 = 3 routes. doesnt work with via points

    key = "route:" + coord_str + ":" + str(params["vehicleWeight"]) + ":" + depart.strftime("%Y%m%d%H") + ":" + str(alternatives)
    cached = cache.get(key)
    span.set_attribute("cache_hit", bool(cached))
    if cached:
        return cached

    res = requests.get(TOMTOM_URL + coord_str + "/json", params=params, headers=HEADERS, timeout=25)
    # free plan has a requests-per-second limit and a plan sends ~6 at once (quick + main +
    # 4 via routes), so some get 429. wait a moment and try again
    for wait in (0.5, 1.5):
        if res.status_code != 429:
            break
        span.add_event("tomtom 429, retrying")
        time.sleep(wait)
        res = requests.get(TOMTOM_URL + coord_str + "/json", params=params, headers=HEADERS, timeout=25)
    # MAP_MATCHING_FAILURE = point isn't near any road (found it in the traces, via points
    # in the himalayas hit this a lot)
    if res.status_code == 400 and ("NO_ROUTE_FOUND" in res.text or "MAP_MATCHING_FAILURE" in res.text):
        raise ValueError("no truck route found between these places")
    if not res.ok:
        # not raise_for_status(), its message has the full url with the api key in it
        # and that ends up in the logs and traces
        raise requests.HTTPError("tomtom returned " + str(res.status_code), response=res)

    routes = []
    for r in res.json()["routes"]:
        coords = []
        for leg in r["legs"]:
            coords += [[p["latitude"], p["longitude"]] for p in leg["points"]]
        # the ETA at each checkpoint needs the driving time to every point of the route.
        # tomtom only gives the time at each instruction ("turn left" at point 120, reached
        # after 3,600 s), not per point. so between two instructions, the time is shared
        # out over the points in between by length: a piece that is 30% of the length gets
        # 30% of the time. assumes the same speed between two turns, close enough.
        # segment_secs[k] = seconds from point k to point k + 1. (plain lat/lon distance
        # instead of miles is fine here, only the ratio matters)
        segment_secs = [0] * (len(coords) - 1)
        instr = r["guidance"]["instructions"]
        for a, b in zip(instr, instr[1:]):
            i, j = a["pointIndex"], b["pointIndex"]
            if j <= i:
                continue  # two instructions at the same point, nothing in between
            secs = b["travelTimeInSeconds"] - a["travelTimeInSeconds"]
            lengths = [math.dist(coords[k], coords[k + 1]) for k in range(i, j)]
            total = sum(lengths)
            for k in range(i, j):
                # share of the time = share of the length (all points in the same place:
                # split it evenly)
                segment_secs[k] = secs * (lengths[k - i] / total if total > 0 else 1 / (j - i))
        routes.append({
            "coords": coords,
            "segment_secs": segment_secs,
            "distance_m": r["summary"]["lengthInMeters"],
            "duration_s": r["summary"]["travelTimeInSeconds"],
        })
    cache.set(key, routes, CACHE_SECONDS)
    return routes


def get_weather(points, start, end):
    # hourly weather for every point from start to end (list in the same order as points)
    with tracer.start_as_current_span("weather") as span:
        return _get_weather(points, start, end, span)


def _get_weather(points, start, end, span):
    start = start.replace(minute=0, second=0, microsecond=0)
    # always get at least 49h (what the heatmap asks for) so the plan and heatmap
    # ask for the same window and share the cache
    hours = max(49, math.ceil((end - start).total_seconds() / 3600))
    end = start + timedelta(hours=hours)

    # snap points to a 0.1 deg grid (~11 km, about the weather model resolution anyway).
    # checkpoints of the 3 routes + heatmap points close together then share one lookup
    cells = [(round(p[0], 1), round(p[1], 1)) for p in points]

    def cache_key(c):
        return "wx:" + str(c[0]) + ":" + str(c[1]) + ":" + start.strftime("%Y%m%d%H") + ":" + str(hours)

    unique = list(set(cells))
    found = cache.get_many([cache_key(c) for c in unique])
    missing = [c for c in unique if cache_key(c) not in found]

    def fetch(batch):
        params = {
            "latitude": ",".join([str(c[0]) for c in batch]),
            "longitude": ",".join([str(c[1]) for c in batch]),
            "hourly": "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "start_hour": start.strftime("%Y-%m-%dT%H:00"),
            "end_hour": end.strftime("%Y-%m-%dT%H:00"),
        }
        res = requests.get(WEATHER_URL, params=params, timeout=30)
        # open meteo's free limit is per minute / hour, a burst (3 heatmaps at once) can hit
        # 429. wait a bit and try again before giving up
        for wait in (1, 3):
            if res.status_code != 429:
                break
            time.sleep(wait)
            res = requests.get(WEATHER_URL, params=params, timeout=30)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict):  # if only 1 point it doesnt return a list
            data = [data]
        out = []
        for d in data:
            h = d["hourly"]
            out.append({
                "wind": [x or 0 for x in h["wind_speed_10m"]],
                "gust": [x or 0 for x in h["wind_gusts_10m"]],
                # rain + showers, open meteo keeps them separate
                "rain": [(a or 0) + (b or 0) for a, b in zip(h["rain"], h["showers"])],
                "snow": [x or 0 for x in h["snowfall"]],
            })
        return out

    # open meteo lets you send many points in one request. big batches (100) were
    # timing out, 25 per request in parallel is a lot faster
    batches = [missing[i:i + 25] for i in range(0, len(missing), 25)]
    results = in_parallel(fetch, batches)

    new = {}
    for batch, weather in zip(batches, results):
        for c, w in zip(batch, weather):
            new[cache_key(c)] = w
    cache.set_many(new, CACHE_SECONDS)
    found.update(new)

    span.set_attribute("points", len(points))
    span.set_attribute("cells", len(unique))
    span.set_attribute("cells_from_cache", len(unique) - len(missing))
    span.set_attribute("requests", len(batches))
    logger.info("weather: %d points, %d cells, %d from cache", len(points), len(unique), len(unique) - len(missing))
    return [found[cache_key(c)] for c in cells]

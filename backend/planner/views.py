import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import services
from .clients import WeatherBusy

logger = logging.getLogger(__name__)

BUSY_MESSAGE = "the weather service (Open-Meteo) is busy right now, try again in a minute"


def parse_time(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def parse_place(p):
    # typed text, or a suggestion the user picked: {"name", "lat", "lon"}
    if isinstance(p, str) and p.strip():
        return p.strip()
    if isinstance(p, dict):
        lat, lon = float(p["lat"]), float(p["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("bad coordinates")
        return {"name": str(p["name"]), "lat": lat, "lon": lon}
    raise ValueError("bad place")


def parse_lines(lines):
    # heatmap input: 1-3 routes, each a list of [lat, lon] points.
    # checked here so a wrong shape is a 400, not a crash deep in build_heatmap
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3:
        raise ValueError("bad lines")
    out = []
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            raise ValueError("bad line")
        points = []
        for p in line:
            if not isinstance(p, list) or len(p) != 2:
                raise ValueError("bad point")
            lat, lon = float(p[0]), float(p[1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("bad coordinates")
            points.append([lat, lon])
        out.append(points)
    return out


def places(request):
    # suggestions for the from / to fields
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"places": []})
    try:
        found = services.suggest_places(q)
    except requests.RequestException as e:
        logger.warning("place search failed: %s", e)
        return JsonResponse({"error": "place search failed"}, status=502)
    return JsonResponse({"places": found})


@csrf_exempt
def plan(request):
    if request.method != "POST":
        return JsonResponse({"error": "use POST"}, status=405)

    try:
        body = json.loads(request.body)
        depart = parse_time(body["depart_at"])
        weight = float(body["weight"])
        interval = int(body.get("interval_mi", 25))
        origin = parse_place(body["origin"])
        destination = parse_place(body["destination"])
        # quick = only the main route, no alternatives. ~3 s instead of ~8 s from tomtom,
        # the frontend asks for this and the full plan at the same time
        quick = bool(body.get("quick", False))
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "missing or invalid fields"}, status=400)

    if interval not in [10, 25, 50]:
        return JsonResponse({"error": "interval has to be 10, 25 or 50"}, status=400)
    if weight <= 0:
        return JsonResponse({"error": "weight has to be more than 0"}, status=400)

    # not in the requirement, my own limit. open-meteo goes ~15 days out but past a week the
    # forecast isnt reliable enough to pick a route on (and trip + 48h heatmap has to fit)
    now = datetime.now(timezone.utc)
    if depart < now - timedelta(hours=2) or depart > now + timedelta(days=7):
        return JsonResponse({"error": "departure has to be within the next 7 days, forecasts further out are not reliable"}, status=400)

    started = time.monotonic()
    try:
        result = services.plan_trip(origin, destination, depart, weight, interval, quick)
    except ValueError as e:
        # no route / place not found
        return JsonResponse({"error": str(e)}, status=422)
    except WeatherBusy as e:
        logger.warning("weather api failed: %s", e)
        return JsonResponse({"error": BUSY_MESSAGE}, status=503)
    except requests.RequestException as e:
        logger.warning("external api failed: %s", e)
        return JsonResponse({"error": "routing or weather service failed, try again"}, status=502)

    logger.info("plan%s %s -> %s: %d routes in %.1fs", " (quick)" if quick else "", origin, destination,
                len(result["routes"]), time.monotonic() - started)
    return JsonResponse(result)


@csrf_exempt
def heatmap(request):
    if request.method != "POST":
        return JsonResponse({"error": "use POST"}, status=405)

    try:
        body = json.loads(request.body)
        depart = parse_time(body["depart_at"])
        weight = float(body["weight"])
        lines = parse_lines(body["lines"])  # checkpoints of each route
        rows = int(body.get("rows", 1))  # corridor width, 1 or 2 rows of points each side
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "missing or invalid fields"}, status=400)
    if rows not in [1, 2]:
        return JsonResponse({"error": "rows has to be 1 or 2"}, status=400)

    started = time.monotonic()
    try:
        result = services.build_heatmap(lines, depart, weight, rows)
    except WeatherBusy as e:
        logger.warning("weather api failed: %s", e)
        return JsonResponse({"error": BUSY_MESSAGE}, status=503)
    except requests.RequestException as e:
        logger.warning("weather api failed: %s", e)
        return JsonResponse({"error": "weather service failed"}, status=502)

    logger.info("heatmap: %d points in %.1fs", len(result["points"]), time.monotonic() - started)
    return JsonResponse(result)

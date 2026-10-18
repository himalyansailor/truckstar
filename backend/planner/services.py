# business logic: checkpoints, risk rules, ranking, heatmap grid

import logging
import math
from datetime import timedelta

from opentelemetry import trace

from . import clients

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


RISK_NAMES = ["Low", "Moderate", "High", "Severe", "No Travel"]


# ---------------------------------------------------------------
# geo helpers
# ---------------------------------------------------------------

def distance_miles(lat1, lon1, lat2, lon2):
    # straight-line distance between two lat/lon points over the earth's surface
    # (haversine formula). lat/lon are angles, not x/y, so plain
    # pythagoras is wrong: 1 deg of longitude is 69 mi at the equator but ~53 mi in denver.
    # 3958.8 = earth radius in miles
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def get_bearing(lat1, lon1, lat2, lon2):
    # compass direction from point 1 to point 2: 0 = north, 90 = east, 180 = south.
    # used to find "sideways" from the road (bearing + 90 / - 90) for the 3rd route and
    # the heatmap. atan2 gives -180..180, the +360 % 360 turns it into 0..360
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def move_point(lat, lon, bearing, miles):
    # the opposite of distance + bearing: start at lat/lon, go `miles` in direction
    # `bearing`, where do you end up. d = the distance as an angle at
    # the earth's centre (miles / earth radius), the formulas need angles
    d = miles / 3958.8
    b = math.radians(bearing)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b))
    lon2 = lon1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def miles_along(coords):
    # miles from the start at each point of the line: [0, 0.3, 0.7, ...].
    # with this "how far along is point k" is a lookup, needed to find where mile 25 is
    out = [0]
    for i in range(1, len(coords)):
        out.append(out[-1] + distance_miles(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]))
    return out


def points_every_n_miles(coords, miles_so_far, secs_so_far, n):
    # the checkpoints. the requirement wants weather every 10 / 25 / 50 miles, but the route from
    # tomtom is just a list of points at random spacing (every few hundred metres, wherever
    # the road bends). no point is exactly at mile 25, so this makes one.
    #
    # coords       = the route points [[lat, lon], ...]
    # miles_so_far = miles from the start at each point  (miles_along)
    # secs_so_far  = seconds of driving to reach each point (from tomtom's timing)
    # returns [mile, lat, lon, seconds] for mile 0, n, 2n, ... and the end
    #
    # 1. the target miles: 0, 25, 50, ... up to the end of the route
    total = miles_so_far[-1]
    targets = []
    m = 0
    while m <= total:
        targets.append(m)
        m += n
    # and the destination itself, unless the last checkpoint is already within a mile of it
    if total - targets[-1] > 1:
        targets.append(total)

    result = []
    j = 0
    for t in targets:
        # 2. find the two route points the target mile lies between: point j is before
        #    it, point j + 1 after. targets only go up, so j never has to go back
        while j < len(miles_so_far) - 2 and miles_so_far[j + 1] < t:
            j += 1
        # 3. how far between them, 0 = at point j, 1 = at point j + 1. e.g. j at mile 24.8,
        #    j + 1 at mile 25.3, target 25 -> frac 0.4. (seg 0 = two points in the same
        #    place, and the clamp handles the end of the route)
        seg = miles_so_far[j + 1] - miles_so_far[j]
        if seg > 0:
            frac = (t - miles_so_far[j]) / seg
        else:
            frac = 0
        frac = max(0, min(1, frac))
        # 4. go that same fraction of the way from j to j + 1, for position and for time.
        #    route points are close together, so a straight line between them is fine.
        #    the time is what gives the checkpoint its ETA, the ETA picks the forecast hour
        lat = coords[j][0] + (coords[j + 1][0] - coords[j][0]) * frac
        lon = coords[j][1] + (coords[j + 1][1] - coords[j][1]) * frac
        secs = secs_so_far[j] + (secs_so_far[j + 1] - secs_so_far[j]) * frac
        result.append([t, lat, lon, secs])
    return result


# ---------------------------------------------------------------
# risk rules (from the requirement)
# ---------------------------------------------------------------

# where each level starts: Moderate, High, Severe, No Travel (below the first = Low).
# same numbers as the requirement's table
THRESHOLDS = {
    "wind": [25, 35, 45, 55],  # mph
    "rain": [0.10, 0.25, 0.50, 1.00],  # in/hr
    "snow": [0.5, 1.0, 2.0, 3.0],  # in/hr
}
# the requirement's ranges share their edges ("0.10–0.25", "0.25–0.50"), so the lower number
# starts the level: 0.25 in/hr is High. except No Travel for rain and snow, written as
# ">1.00" and ">3.0": 1.00 in/hr is still Severe. wind is "≥55 mph", so 55 is No Travel
STRICT_TOP = {"rain", "snow"}
# load rules: a heavy load moves wind one level up. wind level -> above this weight (lb)
# 45–54 mph (Severe) + >30,000 lb -> No Travel, 35–44 mph (High) + >40,000 lb -> Severe
HEAVY_LOAD = {3: 30000, 2: 40000}


def level(condition, value):
    # how many of the 4 thresholds the value has reached = 0 low .. 4 no travel
    *lower, top = THRESHOLDS[condition]
    reached_top = value > top if condition in STRICT_TOP else value >= top
    return sum(value >= t for t in lower) + reached_top


def get_risk(wind, rain, snow, weight):
    # weight in lb, same as the requirement. returns (level 0-4, reasons)
    values = {"wind": wind, "rain": rain, "snow": snow}
    levels = {c: level(c, v) for c, v in values.items()}
    if weight > HEAVY_LOAD.get(levels["wind"], float("inf")):
        levels["wind"] += 1

    reasons = []
    for c, v in values.items():
        if levels[c] > 0:
            reasons.append(c + " " + (str(round(v)) + " mph" if c == "wind" else str(round(v, 2)) + " in/hr"))
    return max(levels.values()), reasons


def smooth_score(wind, rain, snow, weight):
    # for the heatmap only. get_risk gives whole levels (wind 26 and 34 are both 1,
    # Moderate) so the heatmap would jump between 5 flat colours. this gives the position
    # between the thresholds instead: wind 30 is halfway from 25 (Moderate) to 35 (High) =
    # 1.5, so it's drawn between yellow and orange
    def f(v, steps):
        # steps = where each level starts. find the two steps v is between: the result is
        # the lower one's level + how far v is towards the next one (0..1). past the last
        # step = 4, No Travel
        for i in range(len(steps) - 1):
            if v < steps[i + 1]:
                return i + (v - steps[i]) / (steps[i + 1] - steps[i])
        return 4
    s = max(f(v, [0] + THRESHOLDS[c]) for c, v in (("wind", wind), ("rain", rain), ("snow", snow)))
    # never below the real level, so the heavy load rules (which f doesn't know) still show
    risk, _ = get_risk(wind, rain, snow, weight)
    return max(s, risk)


def route_summary(checkpoints):
    # how many miles of the route are at each risk level, for the ranking.
    # weather is only known at the checkpoints, so each stretch between two checkpoints
    # counts as the worse of its two ends
    miles = [0, 0, 0, 0, 0]
    total = 0
    weighted = 0
    for i in range(len(checkpoints) - 1):
        seg = checkpoints[i + 1]["mile"] - checkpoints[i]["mile"]
        # take the worse of the two ends, safer
        risk = max(checkpoints[i]["risk"], checkpoints[i + 1]["risk"])
        miles[risk] += seg
        # avg risk = average over the miles, not over checkpoints (the last stretch
        # before the destination is usually shorter than the rest)
        weighted += risk * seg
        total += seg
    worst = max(c["risk"] for c in checkpoints)
    return {
        "miles_by_level": {RISK_NAMES[i]: round(miles[i], 1) for i in range(5)},
        "no_travel_miles": round(miles[4], 1),
        "severe_miles": round(miles[3], 1),
        "high_miles": round(miles[2], 1),
        "avg_risk": round(weighted / total, 2) if total > 0 else 0,
        "worst": RISK_NAMES[worst],
    }


def sort_key(route):
    # order from the requirement: severe miles, high miles, avg risk, time
    # put no travel first, its worse than severe
    s = route["summary"]
    return (s["no_travel_miles"], s["severe_miles"], s["high_miles"], s["avg_risk"], route["duration_hr"])


def hours_text(hours):
    # 2.42 -> "2h 25m", 0.5 -> "30 min"
    mins = round(abs(hours) * 60)
    return str(mins) + " min" if mins < 60 else str(mins // 60) + "h " + str(mins % 60) + "m"


def why_message(ranked):
    # why the first route won against the next one, and what it costs in time. the ranking
    # is the requirement's order exactly, so a route can win on a small avg risk difference
    # and still be hours longer; saying the time makes that trade-off visible to the driver
    # ("Lower average risk than Route A (0.14 vs 0.28), 4h 25m longer")
    if len(ranked) < 2:
        return "Only one route found."
    best, other = ranked[0], ranked[1]
    s1, s2 = best["summary"], other["summary"]
    name = other["label"]
    if s1["no_travel_miles"] < s2["no_travel_miles"]:
        reason = "Avoids " + str(round(s2["no_travel_miles"] - s1["no_travel_miles"])) + " mi of No Travel conditions on " + name
    elif s1["severe_miles"] < s2["severe_miles"]:
        reason = str(round(s2["severe_miles"] - s1["severe_miles"])) + " fewer Severe miles than " + name
    elif s1["high_miles"] < s2["high_miles"]:
        reason = str(round(s2["high_miles"] - s1["high_miles"])) + " fewer High risk miles than " + name
    elif s1["avg_risk"] < s2["avg_risk"]:
        reason = "Lower average risk than " + name + " (" + str(s1["avg_risk"]) + " vs " + str(s2["avg_risk"]) + ")"
    else:
        reason = "Same weather as " + name + " (avg risk " + str(s1["avg_risk"]) + ")"

    diff = best["duration_hr"] - other["duration_hr"]
    if abs(diff) < 1 / 60:
        return reason + ", same time."
    return reason + ", " + hours_text(diff) + (" longer." if diff > 0 else " faster.")


# ---------------------------------------------------------------
# places
# ---------------------------------------------------------------

# bigger places first, a truck route goes to a town not a hamlet
PLACE_RANK = {"city": 0, "town": 1, "suburb": 2, "village": 3, "hamlet": 4}


def rank_places(text, places):
    # order for the suggestions, the first one is used when the user just typed text:
    # 1. places with exactly the typed name ("Lehra" is a real village, keep it)
    # 2. then bigger places first, so typos land on the city: "Shimal" -> Shimla, not
    #    the village Shimalaya. sorted() keeps photon's order for the same size
    typed = text.split(",")[0].strip().lower()

    def key(p):
        # (not exact name, size rank): exact names sort first, then cities, towns, ...
        exact = p["name"].split(",")[0].strip().lower() == typed
        return (not exact, PLACE_RANK.get(p["type"], 5))

    return sorted(places, key=key)


def best_place(text, places):
    # the place used for typed text: the top of rank_places, or None if nothing matched
    ranked = rank_places(text, places)
    return ranked[0] if ranked else None


def suggest_places(text):
    # the dropdown under the from / to fields: up to 6 places, best first
    return rank_places(text, clients.search_places(text))[:6]


def resolve_place(place):
    # a place picked from the suggestions already has lat/lon, typed text gets searched
    if isinstance(place, dict):
        return place
    return best_place(place, clients.search_places(place))


# ---------------------------------------------------------------
# routes
# ---------------------------------------------------------------

def add_timing(r):
    # cumulative miles + truck seconds at every point of the route
    r["miles_so_far"] = miles_along(r["coords"])
    r["distance"] = r["distance_m"] / 1609.34
    secs = [0]
    for d in r["segment_secs"]:
        secs.append(secs[-1] + d)
    r["secs_so_far"] = secs
    return r


def find_three_routes(a, b, weight, depart):
    # tomtom gives up to 2 alternatives but sometimes there just arent 2 different roads
    # (mountains). then make one by routing through a point off to the side of the middle
    mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    straight = distance_miles(a[0], a[1], b[0], b[1])
    brg = get_bearing(a[0], a[1], b[0], b[1])

    def via_route(t):
        # t = [how far sideways as a share of the trip, which side]. [0.12, 90] = from the
        # midpoint go 12% of the trip distance at 90 deg to the right of the trip
        # direction. at least 10 mi (else it's the same road), at most 90 mi (else a huge
        # detour). tomtom then routes origin -> that point -> destination
        off = min(max(straight * t[0], 10), 90)
        via = move_point(mid[0], mid[1], brg + t[1], off)
        try:
            return add_timing(clients.get_routes([a, via, b], weight, depart, alternatives=False)[0])
        except Exception:
            return None  # no road near the via point etc, just skip it

    routes = [add_timing(r) for r in clients.get_routes([a, b], weight, depart)[:3]]

    if len(routes) >= 3:
        return routes

    # via routes only when tomtom's alternatives aren't enough (mostly mountains). they used
    # to be sent with the main call every time: 6 tomtom calls per trip (quick + main + 4)
    # when 2 were usually enough, more cost, and 6 at once hit tomtom's rate limit.
    # all 4 at once when needed: 2 at a time saved 2 calls but made shimla -> leh 4 s slower
    tries = [[0.12, 90], [0.12, -90], [0.25, 90], [0.25, -90]]
    for r in clients.in_parallel(via_route, tries):
        if len(routes) >= 3:
            break
        if r is None or r["duration_s"] > routes[0]["duration_s"] * 1.5:
            continue  # failed or too much of a detour
        # within 1% of the length of a route we have = most likely the same road
        if not any(abs(e["distance"] - r["distance"]) < e["distance"] * 0.01 for e in routes):
            routes.append(r)
    return routes


def plan_trip(origin_in, dest_in, depart, weight, interval, quick=False):
    # the whole plan for /api/plan/:
    # origin_in / dest_in = typed text or a picked place {name, lat, lon}, depart = datetime
    # (utc), weight = lb, interval = miles between checkpoints (10 / 25 / 50),
    # quick = only tomtom's main route (shown first while the full plan is still running).
    # 1. find both places  2. get the routes  3. checkpoints + ETA along each route
    # 4. weather for all checkpoints in one go  5. risk per checkpoint, summary per route
    # 6. rank the routes, recommended = first. raises ValueError if a place or route
    # isn't found (-> 422 in the view)
    origin, dest = clients.in_parallel(resolve_place, [origin_in, dest_in])
    if origin is None:
        raise ValueError("couldn't find \"" + str(origin_in) + "\" (US or India), pick a place from the suggestions")
    if dest is None:
        raise ValueError("couldn't find \"" + str(dest_in) + "\" (US or India), pick a place from the suggestions")

    a = [origin["lat"], origin["lon"]]
    b = [dest["lat"], dest["lon"]]
    if quick:
        routes_raw = [add_timing(clients.get_routes([a, b], weight, depart, alternatives=False)[0])]
    else:
        with tracer.start_as_current_span("find_three_routes") as span:
            routes_raw = find_three_routes(a, b, weight, depart)
            span.set_attribute("routes", len(routes_raw))

    # get checkpoints for all routes then get weather in one go
    all_checkpoints = []
    all_points = []
    for r in routes_raw:
        cps = points_every_n_miles(r["coords"], r["miles_so_far"], r["secs_so_far"], interval)
        all_checkpoints.append(cps)
        for c in cps:
            all_points.append([c[1], c[2]])

    longest = max(r["duration_s"] for r in routes_raw)
    weather = clients.get_weather(all_points, depart, depart + timedelta(seconds=longest))

    start_hour = depart.replace(minute=0, second=0, microsecond=0)
    routes = []
    idx = 0
    for i in range(len(routes_raw)):
        r = routes_raw[i]
        checkpoints = []
        for c in all_checkpoints[i]:
            eta = depart + timedelta(seconds=c[3])
            w = weather[idx]
            idx += 1
            # weather for the hour closest to when truck gets there. the forecast is a list
            # with one value per hour from the departure hour, so the index is hours since
            # then: eta 14:40, departure hour 09:00 -> 5.7 -> index 6 (15:00)
            h = round((eta - start_hour).total_seconds() / 3600)
            h = max(0, min(h, len(w["wind"]) - 1))
            risk, reasons = get_risk(w["wind"][h], w["rain"][h], w["snow"][h], weight)
            checkpoints.append({
                "mile": round(c[0], 1),
                "lat": round(c[1], 5),
                "lon": round(c[2], 5),
                "eta": eta.isoformat(),
                "wind_mph": round(w["wind"][h], 1),
                "gust_mph": round(w["gust"][h], 1),
                "rain_in": round(w["rain"][h], 3),
                "snow_in": round(w["snow"][h], 3),
                "risk": risk,
                "risk_label": RISK_NAMES[risk],
                "reasons": reasons,
            })

        # tomtom sends thousands of points per route, too much to send and draw. keep a
        # point only if it's > 0.4 mi from the last one kept, the line still looks the same
        line = [r["coords"][0]]
        for p in r["coords"]:
            if distance_miles(line[-1][0], line[-1][1], p[0], p[1]) > 0.4:
                line.append(p)
        line.append(r["coords"][-1])

        routes.append({
            "id": i,
            "label": "Route " + ["A", "B", "C"][i],
            "distance_mi": round(r["distance"], 1),
            "duration_hr": round(r["duration_s"] / 3600, 2),
            "arrive_at": (depart + timedelta(seconds=r["duration_s"])).isoformat(),
            "geometry": [[round(p[0], 5), round(p[1], 5)] for p in line],
            "checkpoints": checkpoints,
        })
        routes[-1]["summary"] = route_summary(checkpoints)

    ranked = sorted(routes, key=sort_key)
    logger.info("ranking: %s", [(r["label"], sort_key(r)) for r in ranked])

    return {
        "origin": origin,
        "destination": dest,
        "depart_at": depart.isoformat(),
        "routes": routes,
        "recommended": ranked[0]["id"],
        "why": why_message(ranked),
    }


# ---------------------------------------------------------------
# heatmap
# ---------------------------------------------------------------

def build_heatmap(lines, depart, weight, rows=1):
    # grid of points around the routes with 48 hours of weather each, so the slider on the
    # frontend doesnt need to call the server again.
    # rows = points on each side of the route: 1 = up to ~15 mi from the road, 2 = ~30 mi
    # (more weather calls, open meteo free limit), so the user picks
    depart = depart.replace(minute=0, second=0, microsecond=0)

    total_miles = 0
    for line in lines:
        total_miles += miles_along(line)[-1]
    # miles between heatmap points: 15, or more for long trips so a route never gets more
    # than ~120 points along it (each point is a weather lookup, free api limit)
    spacing = max(15, total_miles / 120)

    points = []
    seen = set()
    for line in lines:
        m = miles_along(line)
        # points every `spacing` miles along the route. this needs no time, the miles are
        # passed again as the "seconds" just to fill the argument
        samples = points_every_n_miles(line, m, m, spacing)

        for i in range(len(samples)):
            lat, lon = samples[i][1], samples[i][2]
            # direction of the road here, from the point before to the point after (at the
            # ends, itself and its neighbour). bearing + 90 / - 90 = sideways from the road
            prev = samples[max(i - 1, 0)]
            nxt = samples[min(i + 1, len(samples) - 1)]
            brg = get_bearing(prev[1], prev[2], nxt[1], nxt[2])
            # point on the route + `rows` on each side. the wide corridor has all the points of
            # the narrow one, so switching narrow -> wide only fetches the outer row
            candidates = [(lat, lon)]
            for k in range(1, rows + 1):
                candidates += [move_point(lat, lon, brg + 90, spacing * k), move_point(lat, lon, brg - 90, spacing * k)]
            for p in candidates:
                # skip a point if one was already added in the same 0.2 x 0.2 deg square
                # (lat * 5 rounded = steps of 0.2 deg, ~14 mi). happens where routes overlap
                # and where the road bends (side points of the inner curve bunch up)
                key = (round(p[0] * 5), round(p[1] * 5))
                if key in seen:
                    continue
                seen.add(key)
                points.append(p)

    logger.info("heatmap points: %d", len(points))
    weather = clients.get_weather(points, depart, depart + timedelta(hours=48))

    values = []
    for h in range(49):
        row = []
        for w in weather:
            # / 4 = 0..1, what the frontend's colour scale expects
            row.append(round(smooth_score(w["wind"][h], w["rain"][h], w["snow"][h], weight) / 4, 2))
        values.append(row)

    return {
        "start": depart.isoformat(),
        "spacing_mi": round(spacing, 1),
        "points": [[round(p[0], 4), round(p[1], 4)] for p in points],
        "values": values,
    }

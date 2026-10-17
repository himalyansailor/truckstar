from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from planner.clients import WeatherBusy, fetch_weather
from planner.services import best_place, get_risk, route_summary, sort_key, distance_miles, points_every_n_miles


class RiskTest(SimpleTestCase):

    def test_wind(self):
        self.assertEqual(get_risk(24, 0, 0, 1000)[0], 0)
        self.assertEqual(get_risk(25, 0, 0, 1000)[0], 1)
        self.assertEqual(get_risk(44, 0, 0, 1000)[0], 2)
        self.assertEqual(get_risk(55, 0, 0, 1000)[0], 4)

    def test_rain_and_snow(self):
        self.assertEqual(get_risk(0, 0.25, 0, 1000)[0], 2)
        self.assertEqual(get_risk(0, 1.0, 0, 1000)[0], 3)
        self.assertEqual(get_risk(0, 1.01, 0, 1000)[0], 4)
        self.assertEqual(get_risk(0, 0, 3.5, 1000)[0], 4)

    def test_load_rules(self):
        self.assertEqual(get_risk(48, 0, 0, 30001)[0], 4)
        self.assertEqual(get_risk(48, 0, 0, 30000)[0], 3)
        self.assertEqual(get_risk(40, 0, 0, 45000)[0], 3)
        self.assertEqual(get_risk(40, 0, 0, 20000)[0], 2)

    def test_severe_route_loses_even_if_faster(self):
        r1 = {"duration_hr": 5, "summary": route_summary([{"mile": 0, "risk": 0}, {"mile": 25, "risk": 3}, {"mile": 50, "risk": 0}])}
        r2 = {"duration_hr": 7, "summary": route_summary([{"mile": 0, "risk": 0}, {"mile": 25, "risk": 2}, {"mile": 50, "risk": 0}])}
        self.assertEqual(r1["summary"]["severe_miles"], 50)
        self.assertEqual(sorted([r1, r2], key=sort_key)[0], r2)

    def test_points_along_route(self):
        d = distance_miles(0, 0, 0, 1)
        pts = points_every_n_miles([[0, 0], [0, 1]], [0, d], [0, 3600], 25)
        self.assertEqual([round(p[0]) for p in pts], [0, 25, 50, 69])


class PlaceTest(SimpleTestCase):

    def test_typo_goes_to_the_city(self):
        # what photon gives for "Shimal": villages first, the city third
        places = [
            {"name": "Shimalaya, Uttarakhand", "type": "village"},
            {"name": "Shimalya, Uttarakhand", "type": "hamlet"},
            {"name": "Shimla, Himachal Pradesh", "type": "city"},
        ]
        self.assertEqual(best_place("Shimal", places)["name"], "Shimla, Himachal Pradesh")

    def test_exact_name_wins_even_if_small(self):
        places = [
            {"name": "Leh, Ladakh", "type": "city"},
            {"name": "Lehra, Madhya Pradesh", "type": "hamlet"},
        ]
        self.assertEqual(best_place("Lehra", places)["name"], "Lehra, Madhya Pradesh")

    def test_nothing_found(self):
        self.assertIsNone(best_place("asdfghjk", []))


class HeatmapInputTest(SimpleTestCase):

    def test_bad_lines_are_400_not_a_crash(self):
        bad = [
            "not a list",
            [],
            [[{"lat": 39.7, "lon": -105.0}, {"lat": 39.9, "lon": -105.5}]],  # dicts, not [lat, lon]
            [[[39.7, -105.0]]],  # one point
            [[[39.7, -105.0], [999, -105.5]]],  # out of range
        ]
        for lines in bad:
            body = {"depart_at": "2026-10-17T10:00:00Z", "weight": 38000, "lines": lines}
            r = self.client.post("/api/heatmap/", body, content_type="application/json")
            self.assertEqual(r.status_code, 400, lines)


class WeatherRetryTest(SimpleTestCase):
    # fake open meteo answers, no network. cache cleared so the "busy" pause doesn't leak

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def answer(self, status):
        r = mock.Mock(ok=status == 200, status_code=status)
        r.json.return_value = {"hourly": {}}
        return r

    @mock.patch("planner.clients.time.sleep")
    @mock.patch("planner.clients.requests.get")
    def test_busy_then_ok(self, get, sleep):
        get.side_effect = [self.answer(503), requests.Timeout(), self.answer(200)]
        self.assertEqual(fetch_weather({}), {"hourly": {}})
        self.assertEqual(get.call_count, 3)

    @mock.patch("planner.clients.time.sleep")
    @mock.patch("planner.clients.requests.get")
    def test_gives_up_after_3_tries(self, get, sleep):
        get.side_effect = [self.answer(503), self.answer(429), self.answer(503)]
        with self.assertRaises(WeatherBusy):
            fetch_weather({})

    @mock.patch("planner.clients.time.sleep")
    @mock.patch("planner.clients.requests.get")
    def test_pauses_after_giving_up(self, get, sleep):
        get.side_effect = [self.answer(503)] * 3
        with self.assertRaises(WeatherBusy):
            fetch_weather({})
        # next request doesn't call open meteo at all
        with self.assertRaises(WeatherBusy):
            fetch_weather({})
        self.assertEqual(get.call_count, 3)


class RateLimitTest(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_plan_limit_per_minute(self):
        codes = [self.client.post("/api/plan/", {}, content_type="application/json").status_code for _ in range(13)]
        self.assertEqual(codes[:12], [400] * 12)  # bad body, but they still count
        self.assertEqual(codes[12], 429)

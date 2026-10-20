import os
import unittest

from fastapi.testclient import TestClient

from app.server import app

os.environ["INSIGHTS_OFFLINE"] = "1"  # tests must not spend model credit


class AppTest(unittest.TestCase):
    client = TestClient(app)

    def test_index_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/healthz").json()["status"], "ok")

    def test_teams_have_rosters(self):
        teams = self.client.get("/api/teams").json()
        self.assertEqual(len(teams), 4)
        self.assertTrue(all(len(t["players"]) == 11 for t in teams))

    def test_stream_emits_all_channels(self):
        kinds = set()
        with self.client.stream("GET", "/api/stream?speed=600&mode=analyst&lang=es") as r:
            self.assertEqual(r.status_code, 200)
            for line in r.iter_lines():
                if line.startswith("event: "):
                    kinds.add(line[7:])
        self.assertTrue({"meta", "event", "state", "cue", "line", "recap", "trace", "end"} <= kinds, kinds)

    def test_bad_requests_rejected(self):
        self.assertEqual(self.client.get("/api/stream?home=NBR&away=NBR").status_code, 400)
        self.assertEqual(self.client.get("/api/stream?mode=wizard").status_code, 400)


if __name__ == "__main__":
    unittest.main()

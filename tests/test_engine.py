import json
import unittest

from simulator import TEAMS, MatchConfig, expected_goals, pass_difficulty, simulate_match
from simulator.models import PITCH_LENGTH, PITCH_WIDTH


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = simulate_match(TEAMS["NBR"], TEAMS["ASH"], MatchConfig(seed=3))

    def test_deterministic_for_seed(self):
        again = simulate_match(TEAMS["NBR"], TEAMS["ASH"], MatchConfig(seed=3))
        self.assertEqual([e.to_dict() for e in self.events], [e.to_dict() for e in again])

    def test_starts_and_ends(self):
        self.assertEqual(self.events[0].type, "match_start")
        self.assertEqual(self.events[-1].type, "match_end")
        self.assertEqual(sum(e.type == "period_end" for e in self.events), 2)

    def test_clock_never_goes_backwards(self):
        times = [e.t for e in self.events]
        self.assertEqual(times, sorted(times))

    def test_coordinates_on_pitch(self):
        for e in self.events:
            for x, y in ((e.x, e.y), (e.end_x, e.end_y)):
                if x is not None:
                    self.assertTrue(0 <= x <= PITCH_LENGTH and 0 <= y <= PITCH_WIDTH, e)

    def test_score_matches_goals(self):
        goals = [e for e in self.events if e.type == "goal"]
        final = self.events[-1].metrics["final_score"]
        self.assertEqual(final["home"], sum(g.team_id == "NBR" for g in goals))
        self.assertEqual(final["away"], sum(g.team_id == "ASH" for g in goals))

    def test_realistic_volumes(self):
        passes = [e for e in self.events if e.type == "pass"]
        shots = [e for e in self.events if e.type == "shot"]
        accuracy = sum(e.outcome == "complete" for e in passes) / len(passes)
        self.assertTrue(700 <= len(passes) <= 1400, len(passes))
        self.assertTrue(10 <= len(shots) <= 45, len(shots))
        self.assertTrue(0.65 <= accuracy <= 0.9, accuracy)

    def test_serialises_to_json(self):
        for e in self.events:
            json.dumps(e.to_dict())


class MetricsTest(unittest.TestCase):
    def test_xg_higher_closer_to_goal(self):
        self.assertGreater(expected_goals(99, 34), expected_goals(85, 34))
        self.assertGreater(expected_goals(95, 34), expected_goals(95, 10))

    def test_pass_difficulty_bounds_and_pressure(self):
        easy = pass_difficulty(8, 0, False, 40)
        hard = pass_difficulty(40, 25, True, 95)
        self.assertLess(easy, hard)
        self.assertTrue(0 < easy < hard < 1)


if __name__ == "__main__":
    unittest.main()

import unittest

from insights import analyze
from simulator import TEAMS, MatchConfig, simulate_match


def run(seed=7, home="NBR", away="ASH"):
    events = [e.to_dict() for e in simulate_match(TEAMS[home], TEAMS[away], MatchConfig(seed=seed))]
    moments, state = [], None
    for _, found, state in analyze(events):
        moments.extend(found)
    return events, moments, state


class InsightsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.moments, cls.state = run()

    def test_state_matches_raw_events(self):
        snap = self.state.snapshot()
        for tid in (snap["home_id"], snap["away_id"]):
            passes = [e for e in self.events if e["type"] == "pass" and e["team_id"] == tid]
            self.assertEqual(snap["teams"][tid]["passes"], len(passes))
            goals = sum(1 for e in self.events if e["type"] == "goal" and e["team_id"] == tid)
            self.assertEqual(snap["teams"][tid]["goals"], goals)
        self.assertTrue(snap["finished"])

    def test_possession_sums_to_one(self):
        self.assertAlmostEqual(sum(self.state.possession().values()), 1.0, places=2)

    def test_every_goal_is_a_moment_with_evidence(self):
        goals = [e for e in self.events if e["type"] == "goal"]
        goal_moments = [m for m in self.moments if m.type == "goal"]
        self.assertEqual(len(goals), len(goal_moments))
        for m in goal_moments:
            self.assertIn("xg", m.why)
            self.assertIn(m.why["game_state"], {"opener", "equaliser", "go_ahead", "extends_lead", "pulls_one_back"})
            self.assertTrue(m.player_name)

    def test_moments_are_explainable_and_bounded(self):
        self.assertGreater(len(self.moments), 10)
        for m in self.moments:
            self.assertTrue(0 <= m.importance <= 1)
            self.assertTrue(m.why, m)

    def test_pattern_moments_fire(self):
        types = {m.type for _, ms in [(None, run(seed=s)[1]) for s in (7, 11)] for m in ms}
        self.assertTrue({"momentum_shift", "control"} <= types, types)


if __name__ == "__main__":
    unittest.main()

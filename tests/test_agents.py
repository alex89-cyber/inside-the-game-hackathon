import unittest

from agents import Crew, Profile, ungrounded_numbers
from agents.llm import LLMError
from simulator import TEAMS, MatchConfig, simulate_match


def events(seed=7):
    return [e.to_dict() for e in simulate_match(TEAMS["NBR"], TEAMS["ASH"], MatchConfig(seed=seed))]


class LyingClient:
    """Invents a number on the first call, then behaves."""

    name = "liar"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, payload, *, temperature=0.4):
        from agents.offline import respond

        self.calls += 1
        out = respond(payload)
        if payload["task"] == "explain" and "feedback" not in payload:
            out["explanation"] += " That was his 987th touch."
        return out


class BrokenClient:
    name = "broken"

    def complete_json(self, system, payload, *, temperature=0.4):
        raise LLMError("service unavailable")


class CrewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = events()
        cls.profiles = [
            Profile("analyst", "analyst", "en"),
            Profile("fan-es", "casual", "es", favorite_team="ASH"),
            Profile("kid", "kids", "en"),
        ]
        cls.board = Crew(profiles=cls.profiles).run(cls.events)

    def test_every_agent_contributes(self):
        agents = {t["agent"] for t in self.board.trace}
        self.assertEqual(agents, {"analyst", "explainer", "narrator", "personalizer"})
        self.assertEqual([r["phase"] for r in self.board.recaps], ["half_time", "full_time"])

    def test_profiles_get_different_experiences(self):
        analyst = self.board.personalized["analyst"]
        kid = self.board.personalized["kid"]
        self.assertGreater(len(analyst), len(kid))
        self.assertTrue(all(i["language"] == "es" for i in self.board.personalized["fan-es"]))

    def test_every_goal_reaches_every_viewer(self):
        goals = {m["id"] for m in self.board.moments if m["type"] == "goal"}
        for prof in self.profiles:
            delivered = {i["moment_id"] for i in self.board.personalized[prof.id]}
            self.assertTrue(goals <= delivered, prof.id)

    def test_overlay_cues_are_renderable(self):
        for cues in self.board.overlays.values():
            for c in cues:
                for key in ("cue_id", "t_in", "duration_s", "layout", "title", "body", "colors"):
                    self.assertIn(key, c)
                self.assertIn(c["layout"], {"full_banner", "lower_third"})

    def test_insights_are_grounded(self):
        for mid, ins in self.board.insights.items():
            moment = next(m for m in self.board.moments if m["id"] == mid)
            self.assertEqual(ungrounded_numbers(ins["explanation"], {"moment": moment, "x": ins["evidence"], "s": self.board.recaps}), [], ins)

    def test_hallucinated_number_triggers_retry(self):
        client = LyingClient()
        crew = Crew(client=client, profiles=[Profile("a", "analyst")])
        board = crew.run(self.events[:900])
        retries = [t for t in board.trace if t["action"] == "grounding_retry"]
        self.assertTrue(retries)
        self.assertTrue(all("987" not in i["explanation"] for i in board.insights.values()))

    def test_model_outage_falls_back(self):
        board = Crew(client=BrokenClient(), profiles=[Profile("a", "analyst")]).run(self.events)
        self.assertTrue(any(t["action"] == "fallback" for t in board.trace))
        self.assertEqual(len(board.recaps), 2)


class GroundingTest(unittest.TestCase):
    def test_percentages_and_rounding_allowed(self):
        self.assertEqual(ungrounded_numbers("73% of passes, 0.25 xG", {"a": 0.731, "b": 0.249}), [])

    def test_invented_number_caught(self):
        self.assertEqual(ungrounded_numbers("He ran 42 km", {"a": 12}), ["42"])


if __name__ == "__main__":
    unittest.main()

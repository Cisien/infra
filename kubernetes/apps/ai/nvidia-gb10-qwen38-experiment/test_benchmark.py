import unittest

import benchmark


class MultiTurnPayloadTests(unittest.TestCase):
    def test_completion_payload_uses_server_generation_defaults(self):
        payload = benchmark.completion_payload(
            model="test-model",
            prompt="prompt",
            generation_tokens=8,
            cache_salt="cold",
        )

        self.assertNotIn("temperature", payload)

    def test_cached_turn_payload_has_no_cache_salt(self):
        payload = benchmark.completion_payload(
            model="test-model",
            prompt="shared prefix",
            generation_tokens=8,
            cache_salt=None,
        )

        self.assertNotIn("cache_salt", payload)
        self.assertEqual(payload["prompt"], "shared prefix")

    def test_next_turn_preserves_the_previous_prompt_and_completion(self):
        prompt = benchmark.next_turn_prompt(
            previous_prompt="shared prefix",
            completion="assistant answer",
            turn=2,
        )

        self.assertTrue(prompt.startswith("shared prefixassistant answer"))
        self.assertIn("User: Continue turn 2.", prompt)

    def test_cache_benefit_requires_follow_up_ttft_below_threshold(self):
        self.assertTrue(
            benchmark.cache_benefit_verified([10.0, 2.5, 3.0], max_ratio=0.5)
        )
        self.assertFalse(
            benchmark.cache_benefit_verified([10.0, 5.1], max_ratio=0.5)
        )


if __name__ == "__main__":
    unittest.main()

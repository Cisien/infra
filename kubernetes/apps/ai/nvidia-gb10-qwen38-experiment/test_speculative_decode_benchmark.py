import unittest

import speculative_decode_benchmark as benchmark


class CodingWorkloadTests(unittest.TestCase):
    def test_prose_prompt_requests_a_constrained_incident_summary(self):
        prompt = benchmark.prose_prompt()

        self.assertIn("incident summary", prompt)
        self.assertIn("plain text", prompt)
        self.assertIn("Do not use markdown", prompt)

    def test_coding_prompt_requests_a_unified_diff_for_a_parser_fix(self):
        prompt = benchmark.coding_prompt()

        self.assertIn("unified diff", prompt)
        self.assertIn("parse_duration", prompt)
        self.assertIn("milliseconds", prompt)

    def test_cold_payload_uses_a_unique_cache_salt(self):
        payload = benchmark.cold_coding_payload(
            model="test-model", generation_tokens=256, repetition=3
        )

        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(payload["min_tokens"], 256)
        self.assertIn("cache_salt", payload)
        self.assertTrue(payload["cache_salt"].startswith("spec-decode-coding-3-"))

    def test_summary_reports_generation_token_speed_percentiles(self):
        summary = benchmark.summarize_generation_cases(
            [
                {
                    "generation_tokens_per_second": 10.0,
                    "generation_seconds": 20.0,
                    "time_to_first_token_seconds": 2.0,
                },
                {
                    "generation_tokens_per_second": 20.0,
                    "generation_seconds": 10.0,
                    "time_to_first_token_seconds": 1.0,
                },
                {
                    "generation_tokens_per_second": 30.0,
                    "generation_seconds": 5.0,
                    "time_to_first_token_seconds": 0.5,
                },
            ]
        )

        self.assertEqual(summary["samples"], 3)
        self.assertEqual(summary["generation_tokens_per_second"]["median"], 20.0)
        self.assertEqual(summary["generation_tokens_per_second"]["p95"], 30.0)
        self.assertEqual(summary["generation_seconds"]["median"], 10.0)


if __name__ == "__main__":
    unittest.main()

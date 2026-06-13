"""Layer-1 unit tests for harness/lib/utils.py.

Ports every scenario in tests/layer1/test-utils.bats:
  - 5 slugify
  - 2 sprint_pad
  - 2 sprint_dir
  - 4 json_read
  - 3 file_exists
  - 4 init_harness_state
  - 3 update_handoff
  - 2 update_regression_registry
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path

# Ensure the repo root is importable when running via `python -m unittest`
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.helpers.test_helper import HarnessTestCase  # noqa: E402
from harness.lib import utils  # noqa: E402


class SlugifyTests(HarnessTestCase):
    def test_slugify_simple_string(self):
        self.assertEqual(utils.slugify("Hello World"), "hello-world")

    def test_slugify_special_characters_removed(self):
        self.assertEqual(utils.slugify("Build a web-app!!!"), "build-a-web-app")

    def test_slugify_truncates_at_50_chars(self):
        long_input = (
            "this is a very long string that should be truncated at fifty characters exactly"
        )
        result = utils.slugify(long_input)
        self.assertLessEqual(len(result), 50)

    def test_slugify_collapses_multiple_hyphens(self):
        self.assertEqual(utils.slugify("a    b    c"), "a-b-c")

    def test_slugify_no_leading_or_trailing_hyphens(self):
        self.assertEqual(utils.slugify("---test---"), "test")


class SprintPadTests(HarnessTestCase):
    def test_sprint_pad_single_digit(self):
        self.assertEqual(utils.sprint_pad(3), "03")

    def test_sprint_pad_double_digit(self):
        self.assertEqual(utils.sprint_pad(12), "12")


class SprintDirTests(HarnessTestCase):
    def test_sprint_dir_constructs_correct_path(self):
        self.assertEqual(utils.sprint_dir(1), "harness-state/sprints/sprint-01")

    def test_sprint_dir_double_digit_sprint(self):
        self.assertEqual(utils.sprint_dir(10), "harness-state/sprints/sprint-10")


class JsonReadTests(HarnessTestCase):
    def test_json_read_reads_simple_field(self):
        self.install_fixture(
            "config-general.json",
            os.path.join(self.harness_state, "config.json"),
        )
        result = utils.json_read(
            os.path.join(self.harness_state, "config.json"), ".userPrompt"
        )
        self.assertEqual(result, "Build a test project")

    def test_json_read_reads_nested_field(self):
        self.install_fixture(
            "handoff-after-sprint1.json",
            os.path.join(self.harness_state, "handoff.json"),
        )
        result = utils.json_read(
            os.path.join(self.harness_state, "handoff.json"), ".git.harnessBranch"
        )
        self.assertEqual(result, "harness/test-project")

    def test_json_read_returns_empty_for_missing_field(self):
        self.install_fixture(
            "config-general.json",
            os.path.join(self.harness_state, "config.json"),
        )
        result = utils.json_read(
            os.path.join(self.harness_state, "config.json"), ".nonexistent"
        )
        self.assertIn(result, ("", "null"))

    def test_json_read_returns_empty_for_missing_file(self):
        result = utils.json_read("nonexistent-file.json", ".field")
        self.assertEqual(result, "")


class FileExistsTests(HarnessTestCase):
    def test_file_exists_true_for_non_empty_file(self):
        path = os.path.join(self.test_temp_dir, "testfile")
        Path(path).write_text("content\n", encoding="utf-8")
        self.assertTrue(utils.file_exists(path))

    def test_file_exists_false_for_missing_file(self):
        path = os.path.join(self.test_temp_dir, "nonexistent")
        self.assertFalse(utils.file_exists(path))

    def test_file_exists_false_for_empty_file(self):
        path = os.path.join(self.test_temp_dir, "emptyfile")
        Path(path).touch()
        self.assertFalse(utils.file_exists(path))


class InitHarnessStateTests(HarnessTestCase):
    def test_init_creates_all_required_files(self):
        utils.init_harness_state("Test project", "general")
        for rel in (
            "config.json",
            "cost-log.json",
            os.path.join("regression", "registry.json"),
            "progress.md",
        ):
            with self.subTest(file=rel):
                self.assertTrue(
                    Path(self.harness_state, rel).is_file(),
                    f"expected {rel} to exist under {self.harness_state}",
                )

    def test_init_config_contains_prompt_and_type(self):
        utils.init_harness_state("Build something", "cli-tool")
        with open(os.path.join(self.harness_state, "config.json"), encoding="utf-8") as fh:
            config = json.load(fh)
        self.assertEqual(config["userPrompt"], "Build something")
        self.assertEqual(config["projectType"], "cli-tool")

    def test_init_cost_log_starts_empty(self):
        utils.init_harness_state("Test", "general")
        with open(os.path.join(self.harness_state, "cost-log.json"), encoding="utf-8") as fh:
            log = json.load(fh)
        self.assertEqual(len(log["invocations"]), 0)

    def test_init_registry_starts_empty(self):
        utils.init_harness_state("Test", "general")
        with open(
            os.path.join(self.harness_state, "regression", "registry.json"),
            encoding="utf-8",
        ) as fh:
            registry = json.load(fh)
        self.assertEqual(len(registry["sprints"]), 0)


class UpdateHandoffTests(HarnessTestCase):
    def test_update_handoff_creates_handoff_if_missing(self):
        utils.update_handoff(1, "abc123", "harness/sprint-01/pass")
        handoff_path = os.path.join(self.harness_state, "handoff.json")
        self.assertTrue(Path(handoff_path).is_file())
        with open(handoff_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["completedSprints"]), 1)

    def test_update_handoff_adds_sprint_and_updates_git_info(self):
        self.install_fixture(
            "handoff-initial.json",
            os.path.join(self.harness_state, "handoff.json"),
        )
        utils.update_handoff(1, "abc123", "harness/sprint-01/pass")
        with open(os.path.join(self.harness_state, "handoff.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["completedSprints"][0], 1)
        self.assertEqual(data["git"]["latestTag"], "harness/sprint-01/pass")

    def test_update_handoff_idempotent_for_same_sprint(self):
        self.install_fixture(
            "handoff-initial.json",
            os.path.join(self.harness_state, "handoff.json"),
        )
        utils.update_handoff(1, "abc", "tag1")
        utils.update_handoff(1, "def", "tag2")
        with open(os.path.join(self.harness_state, "handoff.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["completedSprints"]), 1)


class UpdateRegressionRegistryTests(HarnessTestCase):
    def test_update_regression_registry_adds_sprint_criteria(self):
        self.install_fixture(
            "registry-empty.json",
            os.path.join(self.harness_state, "regression", "registry.json"),
        )
        os.makedirs(os.path.join(self.harness_state, "sprints", "sprint-01"), exist_ok=True)
        self.install_fixture(
            "contract-sprint01.json",
            os.path.join(self.harness_state, "sprints", "sprint-01", "contract.json"),
        )
        utils.update_regression_registry(1)
        with open(
            os.path.join(self.harness_state, "regression", "registry.json"),
            encoding="utf-8",
        ) as fh:
            registry = json.load(fh)
        self.assertEqual(len(registry["sprints"]["1"]["criteria"]), 3)

    def test_update_regression_registry_no_op_without_contract(self):
        self.install_fixture(
            "registry-empty.json",
            os.path.join(self.harness_state, "regression", "registry.json"),
        )
        utils.update_regression_registry(1)
        with open(
            os.path.join(self.harness_state, "regression", "registry.json"),
            encoding="utf-8",
        ) as fh:
            registry = json.load(fh)
        self.assertEqual(len(registry["sprints"]), 0)


# ---------------------------------------------------------------------------
# Bonus coverage so the contract criteria for log_cost / update_progress /
# logging helpers are exercised by the test suite.
# ---------------------------------------------------------------------------

class LogCostTests(HarnessTestCase):
    def test_log_cost_records_tokens(self):
        utils.init_harness_state("Test", "general")
        utils.log_cost(
            "planner",
            1,
            '{"usage":{"input_tokens":10,"output_tokens":20}}',
        )
        with open(os.path.join(self.harness_state, "cost-log.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["invocations"]), 1)
        entry = data["invocations"][0]
        self.assertEqual(entry["role"], "planner")
        self.assertEqual(entry["sprint"], 1)
        self.assertEqual(entry["inputTokens"], 10)
        self.assertEqual(entry["outputTokens"], 20)

    def test_log_cost_invalid_json_defaults_to_zero(self):
        utils.init_harness_state("Test", "general")
        utils.log_cost("planner", 1, "")
        utils.log_cost("planner", 1, "not-json")
        with open(os.path.join(self.harness_state, "cost-log.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        for entry in data["invocations"]:
            self.assertEqual(entry["inputTokens"], 0)
            self.assertEqual(entry["outputTokens"], 0)


class UpdateProgressTests(HarnessTestCase):
    def test_update_progress_appends_sprint_section(self):
        utils.init_harness_state("Test", "general")
        utils.update_progress(1, "PASS", 1, "abc123")
        text = Path(self.harness_state, "progress.md").read_text(encoding="utf-8")
        self.assertIn("Sprint 01", text)
        self.assertIn("PASS", text)
        self.assertIn("abc123", text)

    def test_update_progress_without_sprint_plan_does_not_crash(self):
        utils.init_harness_state("Test", "general")
        # No sprint-plan.json present
        utils.update_progress(2, "PASS")
        text = Path(self.harness_state, "progress.md").read_text(encoding="utf-8")
        self.assertIn("Sprint 02", text)


class CheckCostCapTests(HarnessTestCase):
    def test_check_cost_cap_returns_none(self):
        utils.init_harness_state("Test", "general")
        self.assertIsNone(utils.check_cost_cap())


class LogHelperTests(HarnessTestCase):
    def _capture(self, fn, message):
        os.environ["NO_COLOR"] = "1"
        buf = io.StringIO()
        original = sys.stderr
        sys.stderr = buf
        try:
            fn(message)
        finally:
            sys.stderr = original
        return buf.getvalue()

    def test_log_info(self):
        out = self._capture(utils.log_info, "hello info")
        self.assertIn("[harness]", out)
        self.assertIn("hello info", out)
        self.assertNotIn("\x1b[", out)

    def test_log_success(self):
        out = self._capture(utils.log_success, "hello success")
        self.assertIn("[harness]", out)
        self.assertIn("hello success", out)
        self.assertNotIn("\x1b[", out)

    def test_log_warn(self):
        out = self._capture(utils.log_warn, "hello warn")
        self.assertIn("[harness]", out)
        self.assertIn("hello warn", out)
        self.assertNotIn("\x1b[", out)

    def test_log_error(self):
        out = self._capture(utils.log_error, "hello error")
        self.assertIn("[harness]", out)
        self.assertIn("hello error", out)
        self.assertNotIn("\x1b[", out)

    def test_log_phase(self):
        out = self._capture(utils.log_phase, "hello phase")
        self.assertIn("[harness]", out)
        self.assertIn("hello phase", out)
        self.assertNotIn("\x1b[", out)


if __name__ == "__main__":
    unittest.main()

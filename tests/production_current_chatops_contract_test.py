from pathlib import Path
from unittest import TestCase


class ProductionCurrentChatopsContractTest(TestCase):
    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "production-current-chatops.yml"
        ).read_text(encoding="utf-8")

    def test_command_is_owner_only_and_scoped_to_control_issue(self) -> None:
        self.assertIn("github.event.issue.number == 39", self.workflow)
        self.assertIn(
            "github.event.comment.user.login == github.repository_owner",
            self.workflow,
        )
        self.assertIn("startsWith(github.event.comment.body, '/release-current ')", self.workflow)
        self.assertIn('["/release-current", "deploy"]', self.workflow)

    def test_current_main_is_resolved_once_to_an_exact_sha(self) -> None:
        self.assertIn(
            'gh api "repos/$GITHUB_REPOSITORY/commits/$DEFAULT_BRANCH" --jq .sha',
            self.workflow,
        )
        self.assertIn("target_commit=$target_commit", self.workflow)
        self.assertIn("^[0-9a-f]{40}$", self.workflow)

    def test_same_locked_sha_runs_preflight_then_apply(self) -> None:
        self.assertEqual(
            self.workflow.count("target_commit: ${{ needs.route.outputs.target_commit }}"),
            2,
        )
        self.assertIn("mode: preflight", self.workflow)
        self.assertIn("if: needs.preflight.result == 'success'", self.workflow)
        self.assertIn("mode: apply", self.workflow)
        self.assertEqual(
            self.workflow.count("uses: ./.github/workflows/production-release.yml"),
            2,
        )

    def test_sender_is_not_implicitly_authorized(self) -> None:
        self.assertIn('values = {"scope": "auto", "include_sender": "false"}', self.workflow)
        self.assertIn("include_sender: ${{ needs.route.outputs.include_sender == 'true' }}", self.workflow)
        self.assertIn("No real email or WeChat probe was requested", self.workflow)

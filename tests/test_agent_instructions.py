from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGIN_GATES = (
    ROOT
    / ".codex"
    / "skills"
    / "job-application-pipeline"
    / "references"
    / "login-gates.md"
)
COMPLETION_SKILL = ROOT / ".agents" / "skills" / "application-completion"


class AgentInstructionTests(unittest.TestCase):
    def test_login_gate_has_only_the_two_credential_paths(self) -> None:
        instructions = LOGIN_GATES.read_text(encoding="utf-8")

        self.assertIn("1. Check the company-login credentials cache", instructions)
        self.assertIn(
            "2. Only when no applicable company credential is available",
            instructions,
        )
        self.assertIn(
            "If the applicable cached credential fails, stop the login attempt",
            instructions,
        )
        self.assertIn("Do not create accounts", instructions)

        for removed_instruction in (
            "application_account_email",
            "application_account_registry_path",
            "account_created",
            "suggested strong password",
            "self-service registration",
        ):
            with self.subTest(removed_instruction=removed_instruction):
                self.assertNotIn(removed_instruction, instructions)

    def test_application_completion_is_registered_and_isolated(self) -> None:
        skill = (COMPLETION_SKILL / "SKILL.md").read_text(encoding="utf-8")
        metadata = (COMPLETION_SKILL / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("name: application-completion", skill)
        self.assertIn("without running the full discovery or application pipeline", skill)
        self.assertIn("Operate on exactly one current or supplied job application", skill)
        self.assertIn("$application-completion", metadata)

        for required_source in (
            ROOT / "application-profile.md",
            ROOT / "COMPLETION_CHECKLIST.md",
            LOGIN_GATES,
        ):
            with self.subTest(required_source=required_source):
                self.assertTrue(required_source.is_file())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGIN_GATES = (
    ROOT
    / ".agents"
    / "skills"
    / "job-application-pipeline"
    / "references"
    / "login-gates.md"
)
LEGACY_COMPLETION_SKILL = ROOT / ".agents" / "skills" / "application-completion"
UNIFIED_COMPLETION_SKILL = (
    ROOT / ".agents" / "skills" / "application-completion-unified"
)
PIPELINE_SKILL = ROOT / ".agents" / "skills" / "job-application-pipeline" / "SKILL.md"
APPLICATION_WORKER = ROOT / ".codex" / "agents" / "application-worker.toml"


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

    def test_legacy_application_completion_remains_available(self) -> None:
        skill = (LEGACY_COMPLETION_SKILL / "SKILL.md").read_text(encoding="utf-8")
        metadata = (
            LEGACY_COMPLETION_SKILL / "agents" / "openai.yaml"
        ).read_text(
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

    def test_unified_application_completion_is_explicit_and_self_contained(
        self,
    ) -> None:
        skill = (UNIFIED_COMPLETION_SKILL / "SKILL.md").read_text(
            encoding="utf-8"
        )
        metadata = (
            UNIFIED_COMPLETION_SKILL / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: application-completion-unified", skill)
        self.assertIn("Operate on exactly one application", skill)
        self.assertIn("../../../application-profile.md", skill)
        self.assertIn("1. Check the company-login credentials cache", skill)
        self.assertIn(
            "2. Only when no applicable cached credential exists",
            skill,
        )
        self.assertIn(
            "ready_for_review` result requires `resume_verified: true",
            skill,
        )
        self.assertNotIn("COMPLETION_CHECKLIST.md", skill)
        self.assertNotIn("login-gates.md", skill)
        self.assertIn("$application-completion-unified", metadata)
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_pipeline_and_worker_invoke_unified_completion(self) -> None:
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        worker = APPLICATION_WORKER.read_text(encoding="utf-8")

        for instructions in (pipeline, worker):
            self.assertIn("application-completion-unified", instructions)
            self.assertNotIn(
                ".agents/skills/application-completion/SKILL.md",
                instructions,
            )

        self.assertIn("$application-completion-unified", pipeline)
        self.assertNotIn("references/login-gates.md", pipeline)
        self.assertIn("resume_verified` may be `true` or `false", pipeline)
        self.assertIn("ready_for_review requires", worker)


if __name__ == "__main__":
    unittest.main()

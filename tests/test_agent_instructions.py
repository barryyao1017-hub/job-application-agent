from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / ".claude"
COMPLETION_SKILL = CLAUDE / "skills" / "application-completion" / "SKILL.md"
PIPELINE_SKILL = CLAUDE / "skills" / "job-application-pipeline" / "SKILL.md"
POLICIES_SKILL = CLAUDE / "skills" / "company-application-policies"
APPLICATION_WORKER = CLAUDE / "agents" / "application-worker.md"
FIT_SCORER = CLAUDE / "agents" / "job-fit-scorer.md"


class AgentInstructionTests(unittest.TestCase):
    def test_login_gate_paths(self) -> None:
        instructions = COMPLETION_SKILL.read_text(encoding="utf-8")

        self.assertIn("1. If the site already recognizes an existing signed-in session", instructions)
        self.assertIn("2. Otherwise, use the agent-vault MCP server", instructions)
        self.assertIn("call `login(account_id)` once", instructions)
        self.assertIn("3. Otherwise, use Chrome's saved-login autofill", instructions)
        self.assertIn("Never type a password or code yourself", instructions)
        self.assertIn('blocker_category: "login_credentials_unavailable"', instructions)
        self.assertIn("Do not create an account", instructions)

        for removed_instruction in (
            "application_account_email",
            "application_account_registry_path",
            "account_created",
            "suggested strong password",
            "self-service registration",
        ):
            with self.subTest(removed_instruction=removed_instruction):
                self.assertNotIn(removed_instruction, instructions)

    def test_completion_skill_is_self_contained(self) -> None:
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")

        self.assertIn("name: application-completion\n", skill)
        self.assertIn("Operate on exactly one application", skill)
        self.assertIn("../../../application-profile.md", skill)
        self.assertTrue((COMPLETION_SKILL.parent / "../../../application-profile.md").resolve().is_file())
        self.assertIn("enqueue-attach.js", skill)
        self.assertIn("Attach the approved résumé with `mcp__claude-in-chrome__file_upload`", skill)
        self.assertIn("Local Resume Companion is the fallback", skill)
        self.assertIn("Read `approved_resume_path` from `config.json`", skill)
        self.assertIn("this worker's own `tabId`", skill)
        self.assertIn("in one `browser_batch` where possible", skill)
        self.assertIn('"Element is no longer in the document", re-run `find` and `file_upload` once', skill)
        self.assertIn("never a Cover Letter input", skill)
        self.assertIn("`input#_systemfield_resume`", skill)
        self.assertIn("`apply-with-resume-container` dropzone", skill)
        self.assertIn('`spl-dropzone[data-test="resume-upload"]`', skill)
        self.assertIn("`iframe#grnhse_iframe`", skill)
        self.assertIn("Fall back to Local Resume Companion only when", skill)
        self.assertIn("The extension's queue is single-slot", skill)
        self.assertIn("Report `resume_verified: true` only then", skill)
        self.assertIn(
            "ready_for_review` result requires `resume_verified: true",
            skill,
        )
        self.assertNotIn("COMPLETION_CHECKLIST.md", skill)
        self.assertNotIn("login-gates.md", skill)

    def test_pipeline_and_worker_use_claude_completion_skill(self) -> None:
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        worker = APPLICATION_WORKER.read_text(encoding="utf-8")

        for instructions in (pipeline, worker):
            with self.subTest(instructions=instructions[:40]):
                self.assertIn(".claude/skills/application-completion/SKILL.md", instructions)
                self.assertNotIn(".agents/", instructions)
                self.assertNotIn("$application-completion", instructions)

        self.assertIn('subagent_type: "application-worker"', pipeline)
        self.assertIn('subagent_type: "job-fit-scorer"', pipeline)
        self.assertNotIn("references/login-gates.md", pipeline)
        self.assertIn("resume_verified` may be `true` or `false", pipeline)
        self.assertIn("ready_for_review requires", worker)
        self.assertIn("disallowedTools: Agent", worker)
        self.assertIn("Attach the résumé with `file_upload`", worker)
        self.assertIn("pinning\nyour own tabId", worker)

    def test_worker_concurrency_blockers_are_named(self) -> None:
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

        self.assertIn("Process workers sequentially for now", pipeline)
        self.assertIn("no longer requires it", pipeline)
        self.assertIn("no longer forces sequencing", pipeline)
        self.assertIn("single-slot queue", pipeline)
        self.assertIn("has not been forward-tested", pipeline)
        self.assertNotIn("singleton attachment queue", pipeline)
        self.assertIn("now the **fallback** attach path", claude_md)
        self.assertIn("`file_upload` first and Local Resume Companion as the fallback", claude_md)

    def test_subagents_are_named_as_referenced(self) -> None:
        self.assertIn("name: application-worker\n", APPLICATION_WORKER.read_text(encoding="utf-8"))
        scorer = FIT_SCORER.read_text(encoding="utf-8")
        self.assertIn("name: job-fit-scorer\n", scorer)
        self.assertIn("tools: Read, Grep, Glob\n", scorer)

    def test_policy_registry_documents_exist(self) -> None:
        import json

        registry = json.loads(
            (POLICIES_SKILL / "references" / "policies.json").read_text(encoding="utf-8")
        )
        for policy in registry["policies"]:
            with self.subTest(policy=policy["id"]):
                self.assertTrue((POLICIES_SKILL / "references" / policy["documentation"]).is_file())


if __name__ == "__main__":
    unittest.main()

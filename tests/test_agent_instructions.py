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
        self.assertIn("4. Otherwise, if the site offers account creation", instructions)
        self.assertIn("Call `register()` once", instructions)
        self.assertIn("call `verify_email(account_id)` once", instructions)
        self.assertIn("Create an account only through agent-vault's `register` tool", instructions)
        self.assertIn("only an exact `site_host` match counts", instructions)
        self.assertNotIn("Do not open registration", instructions)

        for removed_instruction in (
            "application_account_email",
            "application_account_registry_path",
            "account_created",
            "suggested strong password",
            "self-service registration",
        ):
            with self.subTest(removed_instruction=removed_instruction):
                self.assertNotIn(removed_instruction, instructions)

    def test_scheduled_run_may_create_accounts(self) -> None:
        script = (ROOT / "scripts" / "run-automation.sh").read_text(encoding="utf-8")

        self.assertIn("mcp__agent-vault__register", script)
        self.assertIn("mcp__agent-vault__verify_email", script)

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
        self.assertIn("Each enqueue adds its own entry to `attach-queue/`", skill)
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
        self.assertIn("ready_for_review require true", worker)
        self.assertIn("disallowedTools: Agent", worker)
        self.assertIn("Attach the résumé with `file_upload`", worker)
        self.assertIn("pinning\nyour own tabId", worker)

    def test_workers_run_in_parallel_without_sharing_state(self) -> None:
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")
        claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

        self.assertIn("### 4. Delegate applications to parallel workers", pipeline)
        self.assertIn("`max_parallel_workers` from `config.json` (default 2, at most 3)", pipeline)
        self.assertIn("--worker-id daily-browser-worker-N --run-id RUN_ID", pipeline)
        self.assertIn("one Agent call each, so they run at the same time", pipeline)
        self.assertIn("each worker opens and owns its own tab", pipeline)
        self.assertIn("set `max_parallel_workers` to 1 for the next run", pipeline)
        for removed in (
            "Process workers sequentially",
            "Run the worker in the foreground",
            "Run those workers sequentially",
            "single-slot queue",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, pipeline)
                self.assertNotIn(removed, skill)
        self.assertIn("open it in a new tab of your own with `tabs_create_mcp`", skill)
        self.assertIn("set to a marker only your tab carries: `jobtab-`", skill)
        self.assertIn("a page load or redirect resets the title", skill)
        self.assertIn("never a shorter prefix another worker's page could also match", skill)
        self.assertIn("now the **fallback** attach path", claude_md)
        self.assertIn("`file_upload` first and Local Resume Companion as the fallback", claude_md)
        self.assertNotIn("one at a time", claude_md)

    def test_submission_is_gated_and_confirmed(self) -> None:
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        worker = APPLICATION_WORKER.read_text(encoding="utf-8")

        self.assertIn("only when the assignment explicitly says `submit: true`", skill)
        self.assertIn("never click it a second time for the same application", skill)
        self.assertIn("Click the immediate final Submit control exactly once.", skill)
        self.assertIn("Return `submitted` only with visible confirmation evidence.", skill)
        self.assertIn("submission_unconfirmed", skill)
        self.assertIn("identity verification such as an ID photo or selfie", skill)
        self.assertIn("Replace `SUBMIT` with the claim's `submit` value.", pipeline)
        self.assertIn("python3 -m job_agent submit --job-id", pipeline)
        self.assertIn("Submission is the worker's job, never the orchestrator's.", pipeline)
        self.assertIn("only when the assignment says `submit: true`", worker)
        self.assertNotIn("Never click a final Submit button. The pilot ends at Review.", pipeline)

    def test_pipeline_retro_todos_and_recruiter_check(self) -> None:
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")

        self.assertIn("python3 -m job_agent report", pipeline)
        self.assertIn("submitted attempts divided by all finished application attempts", pipeline)
        self.assertIn("there is no daily cap", pipeline)
        self.assertIn("--run-id RUN_ID", pipeline)
        self.assertIn("generalization improvement", pipeline)
        self.assertIn("https://claude.ai/artifact/WSphNhTrrHRRg3DVgEKDhi", pipeline)
        self.assertIn("### 6. Check Gmail for recruiter replies", pipeline)
        self.assertIn("never reply to, label, archive, or forward a recruiter message", pipeline)
        script = (ROOT / "scripts" / "run-automation.sh").read_text(encoding="utf-8")
        self.assertIn("mcp__claude_ai_Gmail__search_threads", script)

    def test_discovery_uses_registry_feeds_not_linkedin(self) -> None:
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")

        self.assertIn("### 2. Discover recent roles", pipeline)
        self.assertIn(
            "python3 -m job_agent fetch-feeds --registry data/company-registry.json --out artifacts/YYYY-MM-DD/discovered.json",
            pipeline,
        )
        self.assertIn("Do not browse LinkedIn or any job board in Chrome to discover roles", pipeline)
        self.assertNotIn("signed-in Chrome LinkedIn session", pipeline)
        self.assertNotIn('"source": "linkedin"', pipeline)
        self.assertTrue((ROOT / "company-registry.example.json").is_file())

    def test_subagents_are_named_as_referenced(self) -> None:
        self.assertIn("name: application-worker\n", APPLICATION_WORKER.read_text(encoding="utf-8"))
        scorer = FIT_SCORER.read_text(encoding="utf-8")
        self.assertIn("name: job-fit-scorer\n", scorer)
        self.assertIn("tools: Read, Grep, Glob\n", scorer)

    def test_fit_scorer_sets_the_skill_score(self) -> None:
        scorer = FIT_SCORER.read_text(encoding="utf-8")
        self.assertIn("model: opus\neffort: high\n", scorer)
        self.assertIn("`data/resume.txt`", scorer)
        self.assertIn("Add `skill_score`, an integer from 0 to 25, and `skill_rationale`", scorer)
        for area in (
            "training ML or AI models",
            "data wrangling",
            "building data pipelines or ETL",
            "A/B testing and experimentation",
            "deploying models to production",
        ):
            self.assertIn(area, scorer)
        self.assertIn("Start at 10", scorer)
        self.assertIn("A résumé gap never\ntakes a role below 10", scorer)
        self.assertIn("keep résumé details and personal\nfacts out of it", scorer)

        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        self.assertIn("python3 -m job_agent resume-text", pipeline)
        self.assertIn("Keep both fields on every candidate when merging", pipeline)

    def test_worker_guards_from_run_retros(self) -> None:
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")

        # JOB-26: an employer identity account reached from the careers site counts.
        self.assertIn("an IBMid (`login.ibm.com`), an Oracle account, an SAP ID", skill)
        self.assertIn("do not decline it for being a general company account", skill)
        self.assertIn("never grant a consent screen", skill)
        self.assertIn("name `idmsa.apple.com` instead of calling `register`", skill)
        # JOB-27: too many tabs make agent-vault time out.
        self.assertIn("Chrome has too many tabs open", skill)
        self.assertIn("retry the same call once", skill)
        # JOB-32: committed values are read from the DOM.
        self.assertIn("Confirm the committed value from the DOM, never from a screenshot alone", skill)
        # JOB-37: required fields are found before the single Submit click.
        self.assertIn("scan the current step for required fields programmatically", skill)
        self.assertIn('`aria-required="true"`', skill)
        self.assertIn("run the required-field scan from section 6 one last time", skill)
        # JOB-38: a changed tab group stops the worker.
        self.assertIn("call `tabs_context_mcp` and note its tab group", skill)
        self.assertIn("do not refill the form in another tab", skill)
        self.assertIn('"tab group changed"', skill)

    def test_application_limits_are_deferred_not_blocked(self) -> None:
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")
        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        policies = (POLICIES_SKILL / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn('`blocker_category: "application_limit"`', skill)
        self.assertIn("When the category is `application_limit`", pipeline)
        self.assertIn("Do not block or claim the company's other jobs by hand", pipeline)
        self.assertIn("python3 -m job_agent limits", pipeline)
        self.assertIn("python3 -m job_agent clear-limit --company COMPANY", pipeline)
        self.assertIn("`limited_company_minimum_fit_score` (default 90)", pipeline)
        self.assertIn("`application_limit` means the company's site caps", policies)
        self.assertIn("### Swap applications at capped companies", pipeline)
        self.assertIn("Withdraw only what `swap-plan` pairs, one pair at a time", pipeline)
        self.assertIn("nothing is ever withdrawn outside it", policies)
        amazon = (POLICIES_SKILL / "references" / "amazon.md").read_text(encoding="utf-8")
        self.assertIn("## Swap procedure", amazon)
        self.assertIn("If Gmail is unavailable, skip the swap this run.", amazon)
        self.assertIn("Workers never withdraw anything.", (COMPLETION_SKILL.parent / "references" / "amazon.md").read_text(encoding="utf-8"))
        self.assertIn("curl -s localhost:9222/json/close/TAB_ID", pipeline)
        script = (ROOT / "scripts" / "run-automation.sh").read_text(encoding="utf-8")
        self.assertIn("Bash(curl -s localhost\\:9222/json/close:*)", script)

    def test_ats_playbooks_exist_and_defer_to_the_skill(self) -> None:
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")
        references = COMPLETION_SKILL.parent / "references"
        for name in ("workday", "greenhouse", "ashby", "lever", "icims", "smartrecruiters", "successfactors", "amazon", "google"):
            with self.subTest(playbook=name):
                self.assertIn(f"`{name}.md`", skill)
                text = (references / f"{name}.md").read_text(encoding="utf-8")
                self.assertIn("SKILL.md` is authoritative", text)
        self.assertIn("where one disagrees with this skill, this skill wins", skill)

    def test_google_and_strong_fits_get_tailored_resumes(self) -> None:
        import json

        pipeline = PIPELINE_SKILL.read_text(encoding="utf-8")
        self.assertIn("python3 -m job_agent tailor-queue --out-dir", pipeline)
        self.assertIn('`subagent_type: "resume-tailor"`', pipeline)
        self.assertIn("a fit of exactly 90 does not count", pipeline)
        self.assertIn("Google applies like any other company (no separate approval)", pipeline)
        self.assertIn("Attach the résumé at `resume_path: RESUME_PATH`", pipeline)
        self.assertIn("SendUserFile", pipeline)
        tailor = (ROOT / ".claude" / "agents" / "resume-tailor.md").read_text(encoding="utf-8")
        self.assertIn("name: resume-tailor\n", tailor)
        self.assertIn("Same facts only.", tailor)
        self.assertIn("Never claim production C++", tailor)
        self.assertIn("python3 -m job_agent render-resume", tailor)
        skill = COMPLETION_SKILL.read_text(encoding="utf-8")
        self.assertIn("The assignment's `resume_path` names the file", skill)
        self.assertIn("caps `skill_score` at 9", FIT_SCORER.read_text(encoding="utf-8"))
        google = json.loads((POLICIES_SKILL / "references" / "policies.json").read_text(encoding="utf-8"))["policies"][0]
        self.assertEqual((google["id"], google["handling"], google["tailor_resume"]), ("google", "auto_apply", True))
        self.assertEqual(
            (google["application_limit"]["max_submissions"], google["application_limit"]["window_days"]), (3, 30)
        )
        self.assertIn("record-applied", (POLICIES_SKILL / "references" / "google.md").read_text(encoding="utf-8"))

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

"""Orchestrator for coordinating Playwright agents with Judge."""

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .judge import JudgeAgent, JudgeVerdict


@dataclass
class WorkflowResult:
    """Result of the full agent workflow."""
    stage: str
    success: bool
    details: str
    judge_verdict: JudgeVerdict | None = None


AgentType = Literal["planner", "generator", "healer"]


class PlaymakerOrchestrator:
    """Coordinates Playwright agents with Judge evaluation."""

    def __init__(
        self,
        project_dir: Path | str = ".",
        loop_type: str = "claude",
        judge_threshold: int = 70,
    ):
        self.project_dir = Path(project_dir)
        self.loop_type = loop_type
        self.judge_threshold = judge_threshold
        self.judge = JudgeAgent()

    def run_playwright_agent(self, agent: AgentType, **kwargs) -> subprocess.CompletedProcess:
        """Run a Playwright agent via CLI."""
        cmd = ["npx", "playwright", agent]

        if agent == "planner" and "request" in kwargs:
            cmd.extend(["--request", kwargs["request"]])

        result = subprocess.run(
            cmd,
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )
        return result

    async def workflow_plan_generate_judge(self, request: str) -> list[WorkflowResult]:
        """Run planner → generator → judge workflow."""
        results = []

        # Step 1: Planner
        print("🎯 Running Planner...")
        planner_result = self.run_playwright_agent("planner", request=request)
        results.append(WorkflowResult(
            stage="planner",
            success=planner_result.returncode == 0,
            details=planner_result.stdout or planner_result.stderr,
        ))

        if planner_result.returncode != 0:
            print("❌ Planner failed")
            return results

        # Step 2: Generator
        print("⚙️ Running Generator...")
        generator_result = self.run_playwright_agent("generator")
        results.append(WorkflowResult(
            stage="generator",
            success=generator_result.returncode == 0,
            details=generator_result.stdout or generator_result.stderr,
        ))

        if generator_result.returncode != 0:
            print("❌ Generator failed")
            return results

        # Step 3: Judge
        print("⚖️ Running Judge...")
        tests_dir = self.project_dir / "tests"
        if tests_dir.exists():
            verdicts = await self.judge.evaluate_directory(tests_dir)

            all_passed = all(v.passed for v in verdicts.values())
            avg_score = sum(v.score for v in verdicts.values()) / len(verdicts) if verdicts else 0

            summary = f"Evaluated {len(verdicts)} tests. Average score: {avg_score:.0f}/100"

            results.append(WorkflowResult(
                stage="judge",
                success=all_passed and avg_score >= self.judge_threshold,
                details=summary,
                judge_verdict=list(verdicts.values())[0] if verdicts else None,
            ))

            if all_passed:
                print(f"✅ Judge approved (avg score: {avg_score:.0f})")
            else:
                print(f"⚠️ Judge found issues (avg score: {avg_score:.0f})")
        else:
            results.append(WorkflowResult(
                stage="judge",
                success=False,
                details="No tests directory found",
            ))

        return results

    async def workflow_full(self, request: str) -> list[WorkflowResult]:
        """Run full workflow: planner → generator → judge → healer."""
        results = await self.workflow_plan_generate_judge(request)

        # Check if judge passed
        judge_result = next((r for r in results if r.stage == "judge"), None)
        if not judge_result or not judge_result.success:
            print("⏭️ Skipping healer - judge issues need manual review")
            return results

        # Step 4: Healer (only if judge passed)
        print("🩹 Running Healer...")
        healer_result = self.run_playwright_agent("healer")
        results.append(WorkflowResult(
            stage="healer",
            success=healer_result.returncode == 0,
            details=healer_result.stdout or healer_result.stderr,
        ))

        if healer_result.returncode == 0:
            print("✅ Healer completed")
        else:
            print("❌ Healer found issues")

        return results

    async def judge_existing_tests(self) -> dict[str, JudgeVerdict]:
        """Judge existing tests without running other agents."""
        tests_dir = self.project_dir / "tests"
        if not tests_dir.exists():
            print(f"❌ Tests directory not found: {tests_dir}")
            return {}

        print(f"⚖️ Judging tests in {tests_dir}...")
        verdicts = await self.judge.evaluate_directory(tests_dir)

        for file_path, verdict in verdicts.items():
            status = "✅" if verdict.passed else "❌"
            print(f"{status} {file_path}: {verdict.score}/100")
            if verdict.issues:
                for issue in verdict.issues:
                    print(f"   - {issue}")

        return verdicts


async def main():
    """Demo the orchestrator."""
    orchestrator = PlaymakerOrchestrator()

    # Judge existing tests (most common use case)
    verdicts = await orchestrator.judge_existing_tests()

    if verdicts:
        avg_score = sum(v.score for v in verdicts.values()) / len(verdicts)
        print(f"\n📊 Average score: {avg_score:.0f}/100")


if __name__ == "__main__":
    asyncio.run(main())

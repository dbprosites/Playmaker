"""Judge agent for evaluating Playwright test quality."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AgentDefinition,
        query,
        AssistantMessage,
        TextBlock,
    )
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


@dataclass
class JudgeVerdict:
    """Result of judge evaluation."""
    passed: bool
    score: int  # 0-100
    issues: list[str]
    suggestions: list[str]
    summary: str


JUDGE_PROMPT = """You are a Playwright test quality judge. Your role is to evaluate generated tests.

Evaluate tests on these criteria:
1. **Selector Quality**: Are locators robust? Prefer role/text selectors over CSS/XPath
2. **Assertions**: Are assertions meaningful and complete?
3. **Test Isolation**: Is each test independent?
4. **Readability**: Clear naming, good structure?
5. **Best Practices**: Follows Playwright conventions?

Respond with JSON:
{
    "passed": true/false,
    "score": 0-100,
    "issues": ["issue1", "issue2"],
    "suggestions": ["suggestion1"],
    "summary": "Brief overall assessment"
}
"""


class JudgeAgent:
    """Judge agent that evaluates Playwright test quality."""

    def __init__(self, model: str = "sonnet"):
        self.model = model
        self._check_sdk()

    def _check_sdk(self):
        if not HAS_SDK:
            print("Warning: claude-agent-sdk not installed. Using fallback mode.")

    async def evaluate_test(self, test_content: str, use_ai: bool = True) -> JudgeVerdict:
        """Evaluate a single test file content."""
        if not use_ai or not HAS_SDK:
            return self._fallback_evaluate(test_content)

        try:
            prompt = f"""Evaluate this Playwright test:

```typescript
{test_content}
```

Provide your verdict as JSON."""

            result = await self._query_claude(prompt)
            if not result:
                # Empty response - fall back to heuristics
                return self._fallback_evaluate(test_content)
            return self._parse_verdict(result)
        except Exception:
            # Fall back to heuristics if SDK fails (e.g., no API key)
            return self._fallback_evaluate(test_content)

    async def evaluate_file(self, file_path: Path) -> JudgeVerdict:
        """Evaluate a test file by path."""
        content = file_path.read_text()
        return await self.evaluate_test(content)

    async def evaluate_directory(self, tests_dir: Path) -> dict[str, JudgeVerdict]:
        """Evaluate all test files in a directory."""
        results = {}
        test_files = list(tests_dir.glob("**/*.spec.ts")) + list(tests_dir.glob("**/*.spec.js"))

        for test_file in test_files:
            results[str(test_file)] = await self.evaluate_file(test_file)

        return results

    async def _query_claude(self, prompt: str) -> str:
        """Query Claude with the judge prompt."""
        options = ClaudeAgentOptions(
            agents={
                "judge": AgentDefinition(
                    description="Test quality evaluator",
                    prompt=JUDGE_PROMPT,
                    tools=["Read"],
                    model=self.model,
                )
            },
            allowed_tools=["Read", "Task"],
        )

        result_text = ""
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "result"):
                result_text = message.result
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text += block.text

        return result_text

    def _parse_verdict(self, response: str) -> JudgeVerdict:
        """Parse Claude's response into a JudgeVerdict."""
        import json
        import re

        # Try to extract JSON block from markdown code fence
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return self._data_to_verdict(data, response)
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object (with balanced braces)
        try:
            start = response.find('{')
            if start != -1:
                brace_count = 0
                for i, char in enumerate(response[start:], start):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            data = json.loads(response[start:i + 1])
                            return self._data_to_verdict(data, response)
        except json.JSONDecodeError:
            pass

        # Fallback if parsing fails
        return JudgeVerdict(
            passed=False,
            score=0,
            issues=["Failed to parse judge response"],
            suggestions=[],
            summary=response[:200] if response else "No response",
        )

    def _data_to_verdict(self, data: dict, raw_response: str) -> JudgeVerdict:
        """Convert parsed JSON data to JudgeVerdict."""
        # Handle various response formats
        issues = data.get("issues", [])
        if issues and isinstance(issues[0], dict):
            # Extract descriptions from nested issue objects
            issues = [i.get("description", str(i)) for i in issues]

        suggestions = data.get("suggestions", data.get("recommendations", []))
        if suggestions and isinstance(suggestions[0], dict):
            suggestions = [s.get("description", str(s)) for s in suggestions]

        # Determine score - may be explicit or inferred from verdict
        score = data.get("score", 0)
        if not score:
            verdict_text = data.get("verdict", "").lower()
            if "excellent" in verdict_text or "good" in verdict_text:
                score = 85
            elif "fair" in verdict_text or "acceptable" in verdict_text:
                score = 70
            elif "poor" in verdict_text:
                score = 40
            else:
                score = 50  # Default middle score

        passed = data.get("passed", score >= 70)

        return JudgeVerdict(
            passed=passed,
            score=score,
            issues=issues,
            suggestions=suggestions,
            summary=data.get("summary", data.get("verdict", raw_response[:100])),
        )

    def _fallback_evaluate(self, test_content: str) -> JudgeVerdict:
        """Simple heuristic evaluation when SDK unavailable."""
        import re

        issues = []
        suggestions = []
        score = 100

        # Check for fragile CSS selectors (both quote styles)
        if re.search(r'page\.locator\(["\']#', test_content) or re.search(r'page\.locator\(["\']\.', test_content):
            issues.append("Uses fragile CSS selectors instead of role/text locators")
            suggestions.append("Use getByRole(), getByText(), or getByTestId()")
            score -= 20

        if "page.waitForTimeout" in test_content:
            issues.append("Uses hardcoded timeouts")
            suggestions.append("Use waitFor conditions instead")
            score -= 15

        if "expect(" not in test_content:
            issues.append("No assertions found")
            score -= 30

        if "test.describe" not in test_content and test_content.count("test(") > 3:
            suggestions.append("Consider grouping related tests with test.describe")
            score -= 5

        return JudgeVerdict(
            passed=score >= 70,
            score=max(0, score),
            issues=issues,
            suggestions=suggestions,
            summary=f"Heuristic evaluation: {score}/100",
        )


async def main():
    """Demo the judge agent."""
    sample_test = '''
import { test, expect } from '@playwright/test';

test('login flow', async ({ page }) => {
    await page.goto('/login');
    await page.locator('#username').fill('testuser');
    await page.locator('#password').fill('password123');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(2000);
    expect(await page.url()).toContain('/dashboard');
});
'''

    judge = JudgeAgent()
    verdict = await judge.evaluate_test(sample_test)

    print(f"Passed: {verdict.passed}")
    print(f"Score: {verdict.score}/100")
    print(f"Issues: {verdict.issues}")
    print(f"Suggestions: {verdict.suggestions}")
    print(f"Summary: {verdict.summary}")


if __name__ == "__main__":
    asyncio.run(main())

"""AI-powered test planner using Anthropic API."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()


class MissingAPIKeyError(Exception):
    """Raised when ANTHROPIC_API_KEY is not set."""
    pass


PLANNER_SYSTEM = """You are a Playwright test planner. Create detailed, actionable test plans.

Output format:
```markdown
# Test Plan: [Title]

## Target
- URL: [target URL]
- Description: [what we're testing]

## Test Scenarios

### Scenario 1: [Name]
- **Given**: [precondition]
- **When**: [action]
- **Then**: [expected result]
- **Selectors**: [suggested Playwright selectors]

### Scenario 2: [Name]
...

## Notes
- [any important considerations]
```

Be specific. Prefer accessible selectors (getByRole, getByText, getByTestId) over CSS.
"""


class PlannerAgent:
    """AI-powered test planner using Claude."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._check_api_key()
        self.client = Anthropic()

    def _check_api_key(self):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingAPIKeyError(
                "ANTHROPIC_API_KEY environment variable is not set.\n"
                "Get your API key from https://console.anthropic.com/\n"
                "Then set it: export ANTHROPIC_API_KEY='sk-ant-...'"
            )

    def plan(self, request: str) -> str:
        """Generate a test plan from a natural language request."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=PLANNER_SYSTEM,
            messages=[
                {"role": "user", "content": f"Create a Playwright test plan for:\n\n{request}"}
            ],
        )
        return message.content[0].text

    def plan_and_save(self, request: str, output_dir: Path = None) -> Path:
        """Generate a test plan and save it to specs directory."""
        plan = self.plan(request)

        if output_dir is None:
            output_dir = Path("specs")

        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename from request
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in request)
        safe_name = safe_name[:50].strip().replace(" ", "-").lower()
        filename = output_dir / f"{safe_name}.md"

        filename.write_text(plan)
        return filename


def main():
    """Demo the planner."""
    planner = PlannerAgent()
    plan = planner.plan("Homepage of example.com contains at least one URL")
    print(plan)


if __name__ == "__main__":
    main()

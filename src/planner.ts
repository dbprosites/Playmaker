import { query } from "@anthropic-ai/claude-agent-sdk";
import * as fs from "fs";
import * as path from "path";

const PLANNER_SYSTEM = fs.readFileSync(
  path.join(process.cwd(), ".claude/agents/playwright-test-planner.md"),
  "utf-8"
);

// Extract just the system prompt (after the frontmatter)
const systemPrompt = PLANNER_SYSTEM.split("---").slice(2).join("---").trim();

async function createTestPlan(url: string): Promise<void> {
  console.log(`Creating test plan for: ${url}`);

  const q = query({
    prompt: `Create a comprehensive test plan for: ${url}

Follow the planner instructions to:
1. Use planner_setup_page to set up the browser
2. Navigate and explore the application
3. Design test scenarios
4. Save the plan using planner_save_plan`,
    options: {
      maxTurns: 50,
      cwd: process.cwd(),
      model: "sonnet",
      systemPrompt,
      allowedTools: [
        "Glob",
        "Grep",
        "Read",
        "LS",
        "Write",
        "mcp__playwright-test__browser_click",
        "mcp__playwright-test__browser_close",
        "mcp__playwright-test__browser_console_messages",
        "mcp__playwright-test__browser_drag",
        "mcp__playwright-test__browser_evaluate",
        "mcp__playwright-test__browser_file_upload",
        "mcp__playwright-test__browser_handle_dialog",
        "mcp__playwright-test__browser_hover",
        "mcp__playwright-test__browser_navigate",
        "mcp__playwright-test__browser_navigate_back",
        "mcp__playwright-test__browser_network_requests",
        "mcp__playwright-test__browser_press_key",
        "mcp__playwright-test__browser_select_option",
        "mcp__playwright-test__browser_snapshot",
        "mcp__playwright-test__browser_take_screenshot",
        "mcp__playwright-test__browser_type",
        "mcp__playwright-test__browser_wait_for",
        "mcp__playwright-test__planner_setup_page",
        "mcp__playwright-test__planner_save_plan",
      ],
      mcpServers: {
        "playwright-test": {
          command: "npx",
          args: ["playwright", "run-test-mcp-server"],
        },
      },
    },
  });

  for await (const message of q) {
    if (message.type === "assistant" && message.message) {
      const textContent = message.message.content.find(
        (c: any) => c.type === "text"
      );
      if (textContent && "text" in textContent) {
        console.log(textContent.text);
      }
    }
  }

  console.log("\nTest plan created in specs/ directory");
}

// CLI
const url = process.argv[2];
if (!url) {
  console.error("Usage: npm run plan <url>");
  console.error("Example: npm run plan https://example.com");
  process.exit(1);
}

createTestPlan(url).catch(console.error);

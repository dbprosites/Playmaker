import { query } from "@anthropic-ai/claude-agent-sdk";
import { execSync } from "child_process";
import { existsSync, readdirSync, readFileSync } from "fs";

interface PRInfo {
  number: number;
  title: string;
  body: string | null;
  files: Array<{ filename: string; status: string; additions: number; deletions: number }>;
  diff: string;
}

/**
 * Initialize Playwright agents if they don't exist.
 */
function ensureAgents(): void {
  if (!existsSync(".claude/agents/playwright-test-planner.md")) {
    console.log("Initializing Playwright agents...");
    execSync("npx playwright init-agents --loop=claude", { stdio: "inherit" });
  }
}

/**
 * Get PR information from GitHub API.
 * Uses GITHUB_TOKEN and environment variables available in GitHub Actions.
 */
async function getPRInfo(): Promise<PRInfo | null> {
  const token = process.env.GITHUB_TOKEN;
  const repository = process.env.GITHUB_REPOSITORY;
  const eventPath = process.env.GITHUB_EVENT_PATH;

  if (!token || !repository || !eventPath) {
    console.log("GitHub environment variables not found. Using mock data.");
    return null;
  }

  // Read PR number from event payload
  const event = JSON.parse(readFileSync(eventPath, "utf-8"));
  const prNumber = event.pull_request?.number;

  if (!prNumber) {
    console.log("No PR number found in event payload. Using mock data.");
    return null;
  }

  const [owner, repo] = repository.split("/");
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github.v3+json",
    "User-Agent": "Playmaker",
  };

  console.log(`Fetching PR #${prNumber} from ${repository}...`);

  // Fetch PR details, files, and diff in parallel
  const [prResponse, filesResponse, diffResponse] = await Promise.all([
    fetch(`https://api.github.com/repos/${owner}/${repo}/pulls/${prNumber}`, { headers }),
    fetch(`https://api.github.com/repos/${owner}/${repo}/pulls/${prNumber}/files`, { headers }),
    fetch(`https://api.github.com/repos/${owner}/${repo}/pulls/${prNumber}`, {
      headers: { ...headers, Accept: "application/vnd.github.v3.diff" },
    }),
  ]);

  if (!prResponse.ok || !filesResponse.ok || !diffResponse.ok) {
    console.log("Failed to fetch PR info from GitHub API. Using mock data.");
    return null;
  }

  const pr = (await prResponse.json()) as { number: number; title: string; body: string | null };
  const files = (await filesResponse.json()) as Array<{
    filename: string;
    status: string;
    additions: number;
    deletions: number;
  }>;
  const diff = await diffResponse.text();

  return {
    number: pr.number,
    title: pr.title,
    body: pr.body,
    files,
    diff: diff.slice(0, 50000), // Limit diff size to avoid token limits
  };
}

/**
 * Format PR info into a summary for the planner.
 */
function formatPRSummary(prInfo: PRInfo): string {
  const filesSummary = prInfo.files
    .map((f) => `- ${f.filename} (${f.status}: +${f.additions}/-${f.deletions})`)
    .join("\n");

  return `## Pull Request #${prInfo.number}: ${prInfo.title}

### Description
${prInfo.body || "No description provided."}

### Files Changed
${filesSummary}

### Diff
\`\`\`diff
${prInfo.diff}
\`\`\``;
}

/**
 * Get change summary - from GitHub PR or mock data.
 */
async function getChangeSummary(): Promise<string> {
  const prInfo = await getPRInfo();

  if (prInfo) {
    return formatPRSummary(prInfo);
  }

  // Fallback mock data for local testing
  return "A search bar has been added to the homepage that allows users to search for products.";
}

async function createTestPlan(): Promise<void> {
  ensureAgents();

  const changeSummary = await getChangeSummary();

  console.log("Change summary:");
  console.log(changeSummary.slice(0, 500) + (changeSummary.length > 500 ? "..." : ""));
  console.log("\nCreating test plan...\n");

  const q = query({
    prompt: `Use the playwright-test-planner agent to create a test plan and SAVE it to specs/ directory.

**What changed:**
${changeSummary}

IMPORTANT: The plan must be saved to a markdown file in the specs/ directory using the Write tool.`,
    options: {
      maxTurns: 50,
      cwd: process.cwd(),
      model: "sonnet",
      allowedTools: [
        "Task",
        "Bash",
        "Glob",
        "Grep",
        "Read",
        "Edit",
        "MultiEdit",
        "Write",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
      ],
    },
  });

  for await (const message of q) {
    if (message.type === "assistant" && message.message) {
      const textContent = message.message.content.find(
        (c: unknown) => (c as { type: string }).type === "text"
      );
      if (textContent && "text" in (textContent as { text?: string })) {
        console.log((textContent as { text: string }).text);
      }
    }
  }

  // Debug: List what's actually in specs/ directory
  console.log("\n--- DEBUG: Checking specs/ directory ---");
  console.log(`Current working directory: ${process.cwd()}`);

  if (existsSync("specs")) {
    const files = readdirSync("specs");
    console.log(`Files in specs/: ${files.join(", ") || "(empty)"}`);
  } else {
    console.log("specs/ directory does not exist!");
  }

  console.log("\nTest plan created in specs/ directory");
}

createTestPlan().catch(console.error);

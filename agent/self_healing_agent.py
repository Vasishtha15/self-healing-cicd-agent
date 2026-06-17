"""
Self-Healing CI/CD Pipeline Agent
----------------------------------
Uses Anthropic Claude to analyse pipeline failures across:
- Dependency installation errors
- Lint failures
- Test failures
- Docker build failures

Posts a structured diagnosis + fix suggestion as a PR comment.
Author: Ayushi Vasishtha
"""

import os
import sys
import json
import requests
from anthropic import Anthropic

# ── Config ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN")
REPO_NAME         = os.environ.get("REPO_NAME")
PR_NUMBER         = os.environ.get("PR_NUMBER")
COMMIT_SHA        = os.environ.get("COMMIT_SHA", "unknown")
RUN_ID            = os.environ.get("RUN_ID", "unknown")
LOG_FILE          = "combined-logs.txt"

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def read_logs() -> str:
    """Read combined pipeline logs from file."""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            content = f.read()
        # Truncate to avoid exceeding context — keep last 8000 chars (most relevant)
        if len(content) > 8000:
            content = "...[truncated]...\n" + content[-8000:]
        return content
    return "No log file found — pipeline may have failed before log collection."


def classify_failures(logs: str) -> dict:
    """
    Quick heuristic classification before sending to Claude.
    Helps Claude focus on the right failure category.
    """
    failures = {
        "install":  any(kw in logs.lower() for kw in ["no module named", "pip", "could not find", "requirement"]),
        "lint":     any(kw in logs.lower() for kw in ["e1", "e2", "e3", "w1", "flake8", "pylint", "undefined name"]),
        "test":     any(kw in logs.lower() for kw in ["failed", "error", "assert", "pytest", "test_"]),
        "docker":   any(kw in logs.lower() for kw in ["dockerfile", "docker", "build failed", "step", "runc"]),
    }
    detected = [k for k, v in failures.items() if v]
    return {"detected": detected, "raw": failures}


def analyse_with_claude(logs: str, failure_context: dict) -> dict:
    """
    Send logs to Claude for deep analysis.
    Returns structured diagnosis and fix suggestions.
    """
    detected_types = ", ".join(failure_context["detected"]) if failure_context["detected"] else "unknown"

    system_prompt = """You are an expert DevOps engineer and CI/CD specialist.
Your job is to analyse pipeline failure logs and provide:
1. A clear root cause diagnosis
2. Specific, actionable fix suggestions with code examples where possible
3. Prevention recommendations

You handle these failure types:
- Dependency/package installation failures
- Lint/code style failures (flake8, pylint)
- Unit/integration test failures (pytest)
- Docker build failures

Always respond in valid JSON with this exact structure:
{
  "severity": "critical|high|medium|low",
  "failure_types": ["list of detected failure types"],
  "root_cause": "Clear one-paragraph explanation of what went wrong",
  "fixes": [
    {
      "type": "install|lint|test|docker",
      "title": "Short fix title",
      "description": "What to do",
      "code": "Exact code/command to fix it (if applicable)"
    }
  ],
  "prevention": "One sentence on how to prevent this in future",
  "confidence": "high|medium|low"
}"""

    user_message = f"""Pipeline failure detected. Failure types identified by heuristics: {detected_types}

Pipeline logs:
{logs}

Analyse these logs and provide your diagnosis and fix suggestions in the required JSON format."""

    print(f"🤖 Sending logs to Claude for analysis (detected: {detected_types})...")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if Claude wrapped in ```json
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    raw_text = raw_text.strip()

    return json.loads(raw_text)


def format_pr_comment(analysis: dict, commit_sha: str, run_id: str, repo: str) -> str:
    """Format Claude's analysis into a clean, readable PR comment."""

    severity_emoji = {
        "critical": "🔴",
        "high":     "🟠",
        "medium":   "🟡",
        "low":      "🟢"
    }.get(analysis.get("severity", "high"), "🟠")

    confidence_emoji = {
        "high":   "✅",
        "medium": "⚠️",
        "low":    "❓"
    }.get(analysis.get("confidence", "medium"), "⚠️")

    failure_badges = " ".join([
        f"`{ft}`" for ft in analysis.get("failure_types", ["unknown"])
    ])

    fixes_md = ""
    for i, fix in enumerate(analysis.get("fixes", []), 1):
        fixes_md += f"\n#### Fix {i}: {fix.get('title', 'Suggested Fix')}\n"
        fixes_md += f"{fix.get('description', '')}\n"
        if fix.get("code"):
            fixes_md += f"\n```bash\n{fix['code']}\n```\n"

    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    comment = f"""## 🤖 Self-Healing CI/CD Agent — Pipeline Analysis

> **Commit:** `{commit_sha[:8]}` | **Severity:** {severity_emoji} `{analysis.get('severity', 'unknown').upper()}` | **Confidence:** {confidence_emoji} `{analysis.get('confidence', 'medium')}`

---

### 🔍 Failure Types Detected
{failure_badges}

---

### 🧠 Root Cause Analysis
{analysis.get('root_cause', 'Unable to determine root cause.')}

---

### 🛠️ Suggested Fixes
{fixes_md}

---

### 🛡️ Prevention
> {analysis.get('prevention', 'No prevention advice available.')}

---

<details>
<summary>📋 Pipeline Run Details</summary>

- **Run ID:** [{run_id}]({run_url})
- **Commit:** `{commit_sha}`
- **Agent Model:** claude-sonnet-4-6
- **Analysis powered by:** [Anthropic Claude](https://www.anthropic.com)

</details>

---
*🤖 This analysis was generated automatically by the [Self-Healing CI/CD Agent](https://github.com/{repo}). Review suggestions carefully before applying.*"""

    return comment


def post_pr_comment(comment: str) -> bool:
    """Post the analysis comment to the GitHub PR."""
    if not PR_NUMBER or PR_NUMBER == "None":
        print("⚠️  No PR number found — this is a direct push, not a PR. Skipping PR comment.")
        print("\n📋 Analysis (would have been posted as PR comment):")
        print(comment)
        return False

    url = f"https://api.github.com/repos/{REPO_NAME}/issues/{PR_NUMBER}/comments"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.post(url, headers=headers, json={"body": comment})

    if response.status_code == 201:
        print(f"✅ Analysis posted to PR #{PR_NUMBER}")
        return True
    else:
        print(f"❌ Failed to post comment: {response.status_code} — {response.text}")
        return False


def main():
    print("🚀 Self-Healing CI/CD Agent starting...")
    print(f"   Repo: {REPO_NAME}")
    print(f"   PR:   #{PR_NUMBER}")
    print(f"   SHA:  {COMMIT_SHA[:8] if COMMIT_SHA else 'unknown'}")

    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set. Exiting.")
        sys.exit(1)

    # 1. Read logs
    logs = read_logs()
    print(f"📄 Logs loaded ({len(logs)} characters)")

    # 2. Quick heuristic classification
    failure_context = classify_failures(logs)
    print(f"🔍 Heuristic detection: {failure_context['detected']}")

    if not failure_context["detected"]:
        print("✅ No failures detected in logs. Pipeline appears healthy.")
        # Still post a success note if it's a PR
        if PR_NUMBER and PR_NUMBER != "None":
            comment = "## 🤖 Self-Healing CI/CD Agent\n\n✅ **Pipeline analysis complete — no failures detected.** All checks passed!\n"
            post_pr_comment(comment)
        return

    # 3. Claude analysis
    try:
        analysis = analyse_with_claude(logs, failure_context)
        print(f"🧠 Claude analysis complete. Severity: {analysis.get('severity', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse Claude response as JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Claude API error: {e}")
        sys.exit(1)

    # 4. Format comment
    comment = format_pr_comment(analysis, COMMIT_SHA, RUN_ID, REPO_NAME)

    # 5. Post to PR
    post_pr_comment(comment)

    # 6. Save analysis locally for debugging
    with open("agent-analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("💾 Analysis saved to agent-analysis.json")

    print("✅ Self-Healing Agent completed successfully.")


if __name__ == "__main__":
    main()

"""
Self-Healing CI/CD Pipeline Agent
----------------------------------
Analyses pipeline failures across:
- Dependency installation errors
- Lint failures (flake8)
- Test failures (pytest)
- Docker build failures

Supports multiple AI providers:
- Anthropic Claude (production)
- Google Gemini (free tier / testing)

Configure via AI_PROVIDER environment variable: "claude" or "gemini"

Posts structured diagnosis + fix suggestions as a PR comment.
Author: Ayushi Vasishtha
"""

import os
import sys
import json
import requests
from typing import Optional

# ── Config ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
AI_PROVIDER       = os.environ.get("AI_PROVIDER", "claude").lower()
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN")
REPO_NAME         = os.environ.get("REPO_NAME")
PR_NUMBER         = os.environ.get("PR_NUMBER")
COMMIT_SHA        = os.environ.get("COMMIT_SHA", "unknown")
RUN_ID            = os.environ.get("RUN_ID", "unknown")
LOG_FILE          = "combined-logs.txt"

SYSTEM_PROMPT = """You are an expert DevOps engineer and CI/CD specialist.
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


def read_logs() -> str:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            content = f.read()
        if len(content) > 8000:
            content = "...[truncated]...\n" + content[-8000:]
        return content
    return "No log file found — pipeline may have failed before log collection."


def classify_failures(logs: str) -> dict:
    failures = {
        "install": any(kw in logs.lower() for kw in ["no module named", "pip", "could not find", "requirement"]),
        "lint":    any(kw in logs.lower() for kw in ["e1", "e2", "e3", "w1", "flake8", "pylint", "undefined name"]),
        "test":    any(kw in logs.lower() for kw in ["failed", "error", "assert", "pytest", "test_"]),
        "docker":  any(kw in logs.lower() for kw in ["dockerfile", "docker", "build failed", "step", "runc"]),
    }
    detected = [k for k, v in failures.items() if v]
    return {"detected": detected, "raw": failures}


def parse_ai_response(raw_text: str) -> dict:
    text = raw_text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    # Find JSON boundaries in case of extra text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
    return json.loads(text)


def analyse_with_claude(logs: str, failure_context: dict) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set.")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    detected_types = ", ".join(failure_context["detected"]) or "unknown"
    print(f"🤖 Sending logs to Anthropic Claude (detected: {detected_types})...")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Pipeline failure detected. Failure types: {detected_types}\n\nLogs:\n{logs}\n\nRespond in JSON only."
        }]
    )
    return parse_ai_response(response.content[0].text)


def analyse_with_gemini(logs: str, failure_context: dict) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")

    detected_types = ", ".join(failure_context["detected"]) or "unknown"
    print(f"🤖 Sending logs to Google Gemini (detected: {detected_types})...")

    combined_prompt = f"""{SYSTEM_PROMPT}

Pipeline failure detected. Failure types identified: {detected_types}

Pipeline logs:
{logs}

Respond in valid JSON only. No markdown, no explanation outside the JSON."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": combined_prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}
    }

    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()

    # Debug: print full raw response
    print(f"📨 Gemini raw response keys: {list(data.keys())}")
    candidate = data.get("candidates", [{}])[0]
    print(f"📨 Finish reason: {candidate.get('finishReason', 'unknown')}")
    raw_text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
    print(f"📨 Raw response length: {len(raw_text)} chars")
    print(f"📨 Raw response preview: {raw_text[:500]}")

    return parse_ai_response(raw_text)


def analyse_with_ai(logs: str, failure_context: dict) -> dict:
    print(f"🔧 AI Provider: {AI_PROVIDER.upper()}")
    if AI_PROVIDER == "gemini":
        return analyse_with_gemini(logs, failure_context)
    elif AI_PROVIDER == "claude":
        return analyse_with_claude(logs, failure_context)
    else:
        raise ValueError(f"Unknown AI_PROVIDER: '{AI_PROVIDER}'. Use 'claude' or 'gemini'.")


def format_pr_comment(analysis: dict, commit_sha: str, run_id: str, repo: str) -> str:
    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
        analysis.get("severity", "high"), "🟠")
    confidence_emoji = {"high": "✅", "medium": "⚠️", "low": "❓"}.get(
        analysis.get("confidence", "medium"), "⚠️")

    provider_label = "Anthropic Claude Sonnet" if AI_PROVIDER == "claude" else "Google Gemini 2.5 Flash"
    provider_badge = "🟣" if AI_PROVIDER == "claude" else "🔵"
    failure_badges = " ".join([f"`{ft}`" for ft in analysis.get("failure_types", ["unknown"])])

    fixes_md = ""
    for i, fix in enumerate(analysis.get("fixes", []), 1):
        fixes_md += f"\n#### Fix {i}: {fix.get('title', 'Suggested Fix')}\n"
        fixes_md += f"{fix.get('description', '')}\n"
        if fix.get("code"):
            fixes_md += f"\n```bash\n{fix['code']}\n```\n"

    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    return f"""## 🤖 Self-Healing CI/CD Agent — Pipeline Analysis

> **Commit:** `{commit_sha[:8]}` | **Severity:** {severity_emoji} `{analysis.get('severity', 'unknown').upper()}` | **Confidence:** {confidence_emoji} `{analysis.get('confidence', 'medium')}` | **AI:** {provider_badge} `{provider_label}`

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
- **AI Provider:** {provider_label}
- **Configured via:** `AI_PROVIDER` environment variable

</details>

---
*🤖 Generated by [Self-Healing CI/CD Agent](https://github.com/{repo}). Supports Anthropic Claude & Google Gemini.*"""


def post_pr_comment(comment: str) -> bool:
    if not PR_NUMBER or PR_NUMBER == "None":
        print("⚠️  No PR number — direct push. Printing analysis:")
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
    print(f"   Repo:     {REPO_NAME}")
    print(f"   PR:       #{PR_NUMBER}")
    print(f"   SHA:      {COMMIT_SHA[:8] if COMMIT_SHA else 'unknown'}")
    print(f"   Provider: {AI_PROVIDER.upper()}")

    if AI_PROVIDER == "claude" and not ANTHROPIC_API_KEY:
        print("❌ AI_PROVIDER=claude but ANTHROPIC_API_KEY not set.")
        sys.exit(1)
    if AI_PROVIDER == "gemini" and not GEMINI_API_KEY:
        print("❌ AI_PROVIDER=gemini but GEMINI_API_KEY not set.")
        sys.exit(1)

    logs = read_logs()
    print(f"📄 Logs loaded ({len(logs)} characters)")

    failure_context = classify_failures(logs)
    print(f"🔍 Detected failures: {failure_context['detected']}")

    if not failure_context["detected"]:
        print("✅ No failures detected — pipeline healthy.")
        if PR_NUMBER and PR_NUMBER != "None":
            post_pr_comment("## 🤖 Self-Healing CI/CD Agent\n\n✅ **No failures detected.** All checks passed!\n")
        return

    try:
        analysis = analyse_with_ai(logs, failure_context)
        print(f"🧠 Analysis complete. Severity: {analysis.get('severity', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse AI response as JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ AI provider error: {e}")
        sys.exit(1)

    comment = format_pr_comment(analysis, COMMIT_SHA, RUN_ID, REPO_NAME)
    post_pr_comment(comment)

    with open("agent-analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("💾 Saved to agent-analysis.json")
    print("✅ Agent completed.")


if __name__ == "__main__":
    main()

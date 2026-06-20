# 🤖 Self-Healing CI/CD Pipeline Agent

> An AI-powered GitHub Actions agent that automatically analyses pipeline failures — across tests, lint, dependencies, and Docker builds — and posts a structured root cause analysis with fix suggestions directly on the PR.

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![Claude AI](https://img.shields.io/badge/Anthropic_Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

---

## 🎯 What It Does

When a CI/CD pipeline fails, engineers spend valuable time reading logs, identifying root causes, and figuring out fixes. This agent automates that entire process using **Anthropic Claude Sonnet**.

**On every pipeline failure, the agent:**
1. Collects logs from all pipeline stages (install, lint, test, Docker)
2. Performs heuristic pre-classification to identify failure types
3. Sends logs to Claude for deep root cause analysis
4. Posts a structured, actionable comment directly on the PR

---

## 🖼️ Example PR Comment Output

```
🤖 Self-Healing CI/CD Agent — Pipeline Analysis

Commit: a1b2c3d4 | Severity: 🟠 HIGH | Confidence: ✅ high

🔍 Failure Types Detected
`test` `docker`

🧠 Root Cause Analysis
The pytest suite failed because the Flask test client fixture is not properly
isolating the app context between tests. The Docker build failed due to a missing
COPY instruction for the tests/ directory...

🛠️ Suggested Fixes

Fix 1: Add app context isolation to pytest fixture
Add app.app_context() to ensure proper Flask context...

  @pytest.fixture
  def client():
      app.config["TESTING"] = True
      with app.app_context():
          with app.test_client() as client:
              yield client

🛡️ Prevention
Add a pre-commit hook running pytest locally before push to catch
test failures before they hit CI.
```

---

## 🏗️ Architecture

```
Pull Request / Push
       │
       ▼
┌─────────────────────────────┐
│   GitHub Actions CI Job     │
│  ┌────────────────────────┐ │
│  │ 1. Install deps        │ │
│  │ 2. Lint (flake8)       │ │──► logs collected
│  │ 3. Run tests (pytest)  │ │
│  │ 4. Docker build        │ │
│  └────────────────────────┘ │
└─────────────────────────────┘
       │ (always runs)
       ▼
┌─────────────────────────────┐
│   Self-Healing Agent Job    │
│                             │
│  1. Read combined logs      │
│  2. Heuristic classification│
│  3. Claude API analysis     │──► Anthropic Claude Sonnet
│  4. Format PR comment       │
│  5. Post via GitHub API     │──► PR Comment
└─────────────────────────────┘
```

---

## 🚀 Setup

### 1. Fork / Clone this repo

```bash
git clone https://github.com/YOUR_USERNAME/self-healing-cicd-agent
cd self-healing-cicd-agent
```

### 2. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key from [console.anthropic.com](https://console.anthropic.com) |

> `GITHUB_TOKEN` is automatically provided by GitHub Actions — no setup needed.

### 3. Push a branch and open a PR

The agent triggers automatically on every PR targeting `main`.

To **test with a deliberate failure**, introduce a syntax error or failing test, push, and watch the agent analyse and comment.

---

## 📁 Project Structure

```
self-healing-cicd-agent/
├── .github/
│   └── workflows/
│       └── ci.yml              # Main pipeline + agent trigger
├── agent/
│   └── self_healing_agent.py   # Core Claude-powered agent
├── sample-app/
│   ├── app.py                  # Demo Flask app
│   ├── requirements.txt
│   ├── Dockerfile
│   └── tests/
│       └── test_app.py
└── README.md
```

---

## ⚙️ Failure Types Handled

| Type | Detected Via | Example |
|------|-------------|---------|
| **Dependency** | pip error keywords | `ModuleNotFoundError`, missing package |
| **Lint** | flake8 error codes | `E302`, `W503`, undefined names |
| **Test** | pytest output | `FAILED`, `AssertionError` |
| **Docker** | build output | `COPY failed`, `RUN` step errors |

---

## 🔧 Customisation

**Add more failure types**: extend `classify_failures()` in `self_healing_agent.py`

**Change the AI model**: update `model="claude-sonnet-4-6"` in `analyse_with_claude()`

**Add Slack notifications**: post the comment body to a Slack webhook after the GitHub PR comment

**Add auto-fix PRs**: extend the agent to use the GitHub API to create a fix branch and PR automatically

---

## 🛠️ Tech Stack

- **CI/CD**: GitHub Actions
- **AI**: Anthropic Claude Sonnet (claude-sonnet-4-6)
- **Language**: Python 3.11
- **GitHub API**: PyGithub + requests
- **Sample App**: Flask + pytest + Docker

---

## 👩‍💻 Author

**Ayushi Vasishtha** — DevOps Engineer | Platform Engineering | AI-Augmented DevOps

Built by Ayushi Vasishtha

[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=flat&logo=linkedin&logoColor=white)](https://linkedin.com/in/ayushivasishtha)

---

## 📄 License

MIT — feel free to use, adapt, and build on this.

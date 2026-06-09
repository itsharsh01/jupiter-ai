# Contributing to GovernAI Agent

Welcome! We are excited that you are interested in contributing to GovernAI. By contributing, you help make AI systems more secure, auditable, and production-ready for everyone.

---

## 🧭 Code of Conduct

We expect all contributors to adhere to standard open-source citizenship:
*   Be respectful, collaborative, and constructive.
*   Focus on technical excellence and objective arguments.
*   Prioritize user privacy and security above all else.

---

## 🛠️ Getting Started with Local Development

GovernAI Agent is built using modern Python tooling. Follow these steps to set up your local development sandbox.

### Prerequisites
*   **Python:** Version 3.14+ (or the version specified in `.python-version`).
*   **uv:** Install [uv](https://docs.astral.sh/uv/) for lightning-fast package management and workspace isolation.

### Local Installation
1.  **Fork and Clone:** Fork the repository on GitHub and clone your fork locally:
    ```bash
    git clone https://github.com/your-username/govern-ai-agent.git
    cd govern-ai-agent
    ```
2.  **Environment Setup:** Create your local configuration file:
    ```bash
    cp .env.example .env
    ```
    Configure the `.env` file with local/test endpoints for **MongoDB**, **Neo4j**, and **Qdrant**.
3.  **Sync Dependencies:** Initialize the virtual environment and install dependencies:
    ```bash
    uv sync
    ```

---

## 🧪 Testing and Linting

Before submitting any code, please ensure your changes pass our quality checks.

### Running Tests
We use `pytest` for unit and integration testing. Run the test suite:
```bash
uv run pytest
```

### Code Formatting & Quality
We adhere to standard Python coding guidelines:
*   Ensure functions have type annotations where applicable.
*   Format code consistently (we recommend using standard formatters like `ruff` or `black`).
*   Verify that your modifications do not break connection test scripts:
    ```bash
    uv run python agent/api/mongo/test_connection.py
    uv run python agent/vector_database/test_connection.py
    uv run python agent/knowledge_graph/load_graph.py --verify
    ```

---

## 📬 How to Contribute

### 1. Reporting Bugs & Requesting Features
*   Check the existing Issues to make sure the topic hasn't already been covered.
*   Open a new Issue using the appropriate bug report or feature request template.
*   Be detailed: include logs, step-by-step reproduction steps, environment details, and expected vs. actual outcomes.

### 2. Submitting Pull Requests (PRs)
1.  **Branching:** Create a descriptive branch from `main`:
    ```bash
    git checkout -b feature/your-feature-name
    # or
    git checkout -b bugfix/issue-description
    ```
2.  **Make Commits:** Write clean, focused commits. Avoid mixing unrelated modifications in a single commit.
3.  **Write Tests:** Add unit tests verifying your new feature or reproducing/fixing the target bug.
4.  **Rebase and Push:** Ensure your branch is rebased on top of the latest `main` branch before pushing:
    ```bash
    git fetch origin
    git rebase origin/main
    git push origin feature/your-feature-name
    ```
5.  **Open Pull Request:** Navigate to the main repository page and click "New Pull Request". Provide a clear summary of what you did, referencing any related issue IDs.

---

## 💡 Contribution Opportunities
If you're looking for areas to contribute, we highly recommend checking:
*   Adding new automated testing strategies in [agent/audit/orchestrator.py](file:///d:/Projects/governai-setup/govern-ai-agent/agent/audit/orchestrator.py).
*   Enhancing PDF and schema parsers for custom company policy ingest.
*   Expanding tracing assertions or adding evaluations for new compliance standards (e.g. SOC2, HIPAA, EU AI Act).

Thank you for contributing to the future of AI governance!

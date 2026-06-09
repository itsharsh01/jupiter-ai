# GovernAI Agent

FinTech AI governance platform: Neo4j knowledge graph, Qdrant vector search, MongoDB customer onboarding, and a FastAPI customer API.

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Setup

```powershell
cd govern-ai-agent
cp .env.example .env
# Edit .env with Neo4j, Qdrant, and MongoDB credentials
uv sync
```

## Environment variables

See [`.env.example`](.env.example) for all keys. Summary:

| Service | Variables |
|---------|-----------|
| Neo4j | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` |
| Qdrant | `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, `EMBEDDING_MODEL` |
| MongoDB | `MONGO_DB_HOST`, `MONGO_DB_USER`, `MONGO_DB_PASSWORD`, `MONGO_DB_NAME` |

---

## Connection testing

Run these from the `govern-ai-agent` directory after configuring `.env`.

### MongoDB

```powershell
uv run python agent/api/mongo/test_connection.py
```

Expected output includes `MongoDB connection OK` and database/collection names.

### Qdrant

```powershell
uv run python agent/vector_database/test_connection.py
```

Expected output includes `Qdrant connection OK` and a list of collections.

### Neo4j

There is no separate ping script; verify by loading the ontology with `--verify` (connects, loads, prints node/relationship counts):

```powershell
uv run python agent/knowledge_graph/load_graph.py --verify
```

For a quick connectivity check without loading data, use the export step (read-only query):

```powershell
uv run python agent/knowledge_graph/export_graph.py
```

### API health (Mongo + server)

Start the API, then call health:

```powershell
uv run python agent/api/run_api.py
```

In another terminal:

```powershell
curl http://localhost:8800/health
```

Or open http://localhost:8800/docs for the interactive Swagger UI.

---

## Data setup commands

### Neo4j — load knowledge graph

```powershell
uv run python agent/knowledge_graph/load_graph.py --verify
```

Options:

```powershell
uv run python agent/knowledge_graph/load_graph.py --no-wipe
uv run python agent/knowledge_graph/load_graph.py --verify
```

### Qdrant — index ontology embeddings

```powershell
uv run python agent/vector_database/index_nodes.py --recreate --verify
```

Options:

```powershell
uv run python agent/vector_database/index_nodes.py --dry-run
uv run python agent/vector_database/index_nodes.py --recreate
uv run python agent/vector_database/index_nodes.py --model all-MiniLM-L6-v2
```

### Graph viewer (browser)

```powershell
uv run python agent/knowledge_graph/export_graph.py
cd agent/knowledge_graph
python -m http.server 8080
```

Open http://localhost:8080/view_graph.html

---

## Customer API

```powershell
uv run python agent/api/run_api.py
```

If **port 8800 is already in use**, stop the other instance (`taskkill /PID <pid> /F` — the startup error shows the PID) or set `API_PORT` to another value in `.env`.

- Host/port: `127.0.0.1:8800` by default (`API_HOST`, `API_PORT` in `.env`)
- Base URL: http://127.0.0.1:8800
- Docs: http://127.0.0.1:8800/docs
- Do not use `API_RELOAD=true` on Windows unless needed (can prevent the port from binding)
- Customers: `/api/v1/customers`
- Form options: `/api/v1/meta/options`

Policy PDFs are stored locally under `data/uploads/{customer_id}/policies/`. Customer records are stored in MongoDB.

---

## Deployment (Google App Engine)

**Project:** `jupiter-ai-498513`  
**API URL:** https://jupiter-ai-498513.uc.r.appspot.com

### Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`) authenticated to the project
- Dependencies exported to `requirements.txt` before each deploy:

```powershell
uv export --no-dev --no-editable --no-emit-project -o requirements.txt
```

### One-time setup

1. **IAM** (new GCP projects only — fixes opaque deploy errors):

```powershell
.\scripts\setup_gae_iam.ps1 -ProjectId jupiter-ai-498513
```

2. **Production secrets** — create `.env.production.yaml` (gitignored) from `.env`:

```yaml
env_variables:
  NEO4J_URI: "..."
  NEO4J_USER: "..."
  NEO4J_PASSWORD: "..."
  NEO4J_DATABASE: "..."
  QDRANT_URL: "..."
  QDRANT_API_KEY: "..."
  MONGO_DB_HOST: "..."
  MONGO_DB_USER: "..."
  MONGO_DB_PASSWORD: "..."
  GROQ_API_KEY: "..."
  PHOENIX_API_KEY: "..."
  PHOENIX_COLLECTOR_ENDPOINT: "..."
  GOVERN_AUTH_SECRET: "..."
  GOVERN_AUTH_DEMO_EMAIL: "root@gov.os"
  GOVERN_AUTH_DEMO_PASSWORD: "governai-dev"
```

See [`.env.example`](.env.example) for all keys.

### Deploy API

```powershell
.\scripts\deploy.ps1
```

Or manually:

```powershell
python scripts/merge_deploy_yaml.py app.yaml .env.production.yaml .app.deploy.yaml
gcloud app deploy .app.deploy.yaml --project=jupiter-ai-498513
Remove-Item .app.deploy.yaml
```

### Verify

```powershell
curl https://jupiter-ai-498513.uc.r.appspot.com/health
```

The Pub/Sub audit worker deploys separately via `worker-app.yaml` (Cloud Run).

---

## Project layout

```
govern-ai-agent/
├── agent/
│   ├── api/                 # FastAPI customer onboarding
│   │   ├── mongo/           # MongoDB connection + repository
│   │   └── run_api.py
│   ├── knowledge_graph/     # Neo4j ontology load & export
│   └── vector_database/     # Qdrant embeddings
├── data/
│   └── uploads/             # Local policy PDF storage
├── .env.example
└── pyproject.toml
```

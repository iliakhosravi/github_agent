# GitHub Agent

A local Flask service that lets a user send a natural-language prompt and have an
LLM agent edit one of their GitHub repositories — reading files, creating a
branch, committing, and opening a pull request.

- **Agent**: LangGraph (explicit `agent → tools → agent` loop)
- **GitHub access**: the remote **GitHub MCP server** (`https://api.githubcopilot.com/mcp/`), called with each user's own token
- **Storage**: PostgreSQL — users, encrypted tokens, chat sessions, messages
- **Memory**: the last 3 messages of the chat are replayed as context (configurable)
- **LLM**: pluggable — OpenAI by default, swap to Anthropic / Google / Groq / Ollama with one env var

---

## How it fits together

```
POST /api/chat
   │
   ├─ resolve user (external_id) ──► PostgreSQL
   ├─ decrypt that user's GitHub token (Fernet), refresh if expired
   ├─ load the last N messages of the session as context
   │
   ├─ open an MCP session to the GitHub MCP server
   │      Authorization: Bearer <this user's token>
   │      X-MCP-Toolsets: context,repos,issues,pull_requests
   │  ──► tools are loaded as LangChain tools
   │
   ├─ LangGraph loop:  agent ⇄ tools   (until the model stops calling tools)
   │
   └─ persist the turn, return {reply, tool_calls, session_id}
```

One MCP session per request, carrying that user's token — nothing is shared
between users, and the agent's reach is exactly the reach of the token.

---

## Layout

```
run.py                     entrypoint
app/
  __init__.py              app factory, blueprints, error handlers
  config.py                all env-driven settings
  extensions.py            db / migrate instances
  models.py                User, GitHubCredential, ChatSession, ChatMessage
  cli.py                   flask init-db / genkey / add-token
  security/crypto.py       Fernet encryption for tokens at rest
  services/
    token_service.py       store / fetch / refresh GitHub tokens
    chat_service.py        sessions + the rolling 3-message memory
    errors.py              typed errors → HTTP status codes
  agent/
    llm.py                 pluggable LLM factory
    mcp_client.py          GitHub MCP connection (streamable HTTP)
    prompts.py             system prompt + branch/PR policy
    graph.py               the LangGraph state machine
    runner.py              sync Flask ⇄ async agent bridge
    service.py             orchestration for one turn
  auth/routes.py           OAuth flow + PAT registration
  api/routes.py            /api/chat, sessions, tools, health
tests/test_app.py          smoke tests (no token or API key needed)
```

---

## Setup

```bash
cd /Users/ilia/Projects/github_agent

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Start Postgres (or point `DATABASE_URL` at an existing one):

```bash
docker compose up -d db
```

Fill in `.env`:

```bash
# a real encryption key for tokens at rest
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → paste into TOKEN_ENCRYPTION_KEY

# and set OPENAI_API_KEY
```

Create the tables:

```bash
export FLASK_APP=run.py
flask init-db                 # quick start
# or, with migrations:
flask db init && flask db migrate -m "initial" && flask db upgrade
```

Run it:

```bash
python run.py                 # http://127.0.0.1:5000
```

---

## Connecting a GitHub account

**Option A — personal access token** (fastest):

```bash
curl -X POST http://127.0.0.1:5000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "ilia", "token": "ghp_xxx", "default_repo": "ilia/my-repo"}'
```

The token needs the `repo` scope (fine-grained tokens: Contents + Pull requests
read/write on the repos you want the agent to touch).

**Option B — OAuth**: create an OAuth App at
GitHub → Settings → Developer settings → OAuth Apps, with callback URL
`http://127.0.0.1:5000/auth/github/callback`. Put the client id/secret in `.env`,
then open:

```
http://127.0.0.1:5000/auth/github/login?user_id=ilia
```

The `state` parameter is a signed, time-limited token carrying the user id, so
no server-side state table is needed and forged callbacks are rejected.

---

## Using the agent

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
        "user_id": "ilia",
        "repo": "ilia/my-repo",
        "message": "Add retry with exponential backoff to the HTTP client in src/client.py"
      }'
```

```json
{
  "session_id": "6f1c…",
  "repo": "ilia/my-repo",
  "reply": "Opened PR #12 from branch agent/add-retry-backoff …",
  "tool_calls": [{"name": "get_file_contents", "args": {"path": "src/client.py"}}, …],
  "history_used": 0
}
```

Pass the returned `session_id` on the next call to continue the conversation —
the last 3 messages are replayed as context.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat` | send a prompt to the agent |
| GET | `/api/sessions?user_id=` | list a user's chats |
| GET | `/api/sessions/<id>/messages?user_id=` | full transcript |
| GET | `/api/tools?user_id=` | which MCP tools this token exposes (debug) |
| GET | `/api/health` | DB + config status |
| GET | `/auth/github/login?user_id=` | start OAuth |
| GET | `/auth/github/callback` | OAuth callback |
| POST | `/auth/token` | store a PAT |
| GET | `/auth/status?user_id=` | is this user connected |
| DELETE | `/auth/token?user_id=` | remove stored token |

---

## Swapping the LLM

Config only:

```bash
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
ANTHROPIC_API_KEY=...
```

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:14b
OLLAMA_BASE_URL=http://localhost:11434
```

Install the matching package (`langchain-anthropic`, `langchain-ollama`, …) —
they are listed, commented out, in `requirements.txt`.

Per-request override:

```json
{"user_id": "ilia", "message": "...", "llm": {"provider": "anthropic", "model": "claude-sonnet-4-5"}}
```

Adding a provider = one function plus one entry in `_BUILDERS` in `app/agent/llm.py`.

---

## Other knobs

| Variable | Default | Effect |
|---|---|---|
| `CHAT_HISTORY_LIMIT` | `3` | messages replayed as context |
| `AGENT_WRITE_MODE` | `branch_pr` | `branch_pr` or `direct_commit` |
| `GITHUB_MCP_TOOLSETS` | `context,repos,issues,pull_requests` | narrows the tool list; `all` for everything |
| `GITHUB_MCP_READONLY` | `false` | `true` makes the MCP server reject writes |
| `AGENT_RECURSION_LIMIT` | `40` | max agent↔tool round trips |
| `AGENT_TIMEOUT_SECONDS` | `300` | per-request ceiling |

---

## Tests

```bash
pytest -q
```

Nine tests, all offline — they cover token encryption round-trip, the
3-message memory window, MCP header construction, prompt modes, the error
contract, and the full agent loop driven by a fake model and a fake tool.

---

## Notes

- Tokens are encrypted with Fernet before they reach the database; the key comes
  from `TOKEN_ENCRYPTION_KEY` (derived from `SECRET_KEY` in dev, with a warning).
- Flask is synchronous, the agent is async: `app/agent/runner.py` keeps one
  background event loop for the process rather than tearing one down per request.
- `/api/chat` has no authentication of its own — `user_id` is trusted. Put this
  behind your own auth before exposing it beyond localhost.
- The agent is instructed never to push to the default branch; it branches and
  opens a PR. `AGENT_WRITE_MODE=direct_commit` changes that instruction.

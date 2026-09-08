Here's the same walkthrough, container-first. Make sure Docker Desktop is running.

## Before you start

You'll need a GitHub personal access token (fine-grained: *Contents* and *Pull requests* read & write, *Metadata* read — or classic with the `repo` scope) and an OpenAI key. Create a throwaway repo to test against, say `ilia/agent-scratch`, with a README in it so there's something to read.

## 1. Configure

```bash
cd /Users/ilia/Projects/github_agent
cp .env.example .env
```

Generate an encryption key. You don't need a local Python environment for this — borrow the image's:

```bash
docker run --rm python:3.12-slim sh -c "pip install -q cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

Edit `.env` and set four things:

```
SECRET_KEY=any-long-random-string
TOKEN_ENCRYPTION_KEY=<the key you just generated>
OPENAI_API_KEY=sk-...
GITHUB_MCP_READONLY=true
```

That last one is deliberate for the first pass — GitHub's MCP server will reject every write, so you can confirm auth and connectivity before the agent can touch anything.

Leave `DATABASE_URL` as it is. Compose overrides it, because inside the container network the database is `db`, not `localhost`.

## 2. Build and start everything

```bash
docker compose --profile app up --build
```

First build takes a few minutes. Watch for these lines in order: Postgres reporting healthy, `Tables created.`, then gunicorn `Listening at: http://0.0.0.0:5000`.

Leave it in the foreground so you can see the logs, and open a second terminal for the rest. (Or use `-d` and `docker compose logs -f app`.)

## 3. Run the offline tests inside the container

```bash
docker compose --profile app run --rm app pytest -q
```

Expect `9 passed`. This proves the image is built correctly — nothing here touches GitHub or the LLM.

## 4. Is it alive

```bash
curl -s localhost:5000/api/health | python3 -m json.tool
```

`"database": true` is what you want. If it's false, the app came up before Postgres was ready — `docker compose logs db` will say.

## 5. Store your token

```bash
curl -X POST localhost:5000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","token":"ghp_YOUR_TOKEN","default_repo":"ilia/agent-scratch"}'
```

The response echoes your GitHub login — that's the service having verified the token against `GET /user`. A `401 invalid_token` means the token is wrong or under-scoped, and nothing was stored.

## 6. Check the MCP connection

```bash
curl -s "localhost:5000/api/tools?user_id=ilia" | python3 -m json.tool
```

This is the important one. It opens a real MCP session with your token and lists what came back — **without involving the LLM at all**, so it separates "GitHub or MCP is broken" from "the model is misbehaving." You should see a few dozen tools: `get_file_contents`, `create_branch`, `create_pull_request`, and so on.

If this fails, stop here. Nothing downstream can work.

## 7. A read-only agent turn

```bash
curl -X POST localhost:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","repo":"ilia/agent-scratch",
       "message":"List the files in the root of this repo and tell me what it contains."}'
```

Check three things: `reply` should describe your actual repo (vague or generic means it didn't really call tools), `tool_calls` should be non-empty, and copy the `session_id`.

## 8. Does it remember

```bash
curl -X POST localhost:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","session_id":"PASTE_ID","message":"What did I just ask you?"}'
```

`history_used` should be above zero and the reply should refer back. That's the 3-message window.

## 9. Turn off read-only and make a real change

Environment is read when the container is created, so editing `.env` needs a recreate, not a restart:

```bash
# set GITHUB_MCP_READONLY=false in .env, then:
docker compose --profile app up -d --force-recreate app
```

```bash
curl -X POST localhost:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","repo":"ilia/agent-scratch",
       "message":"Add a file HELLO.md at the repo root with one line saying hello, and open a pull request for it."}'
```

Now look at GitHub. You want a new branch and an open PR. If you find a commit sitting directly on `main`, the branch-and-PR instruction isn't holding — tell me, that's a real bug.

## 10. Check what was stored

```bash
curl -s "localhost:5000/api/sessions/PASTE_ID/messages?user_id=ilia" | python3 -m json.tool
```

Every turn with its tool calls — the full transcript, not just the window the model sees.

And to confirm tokens really are encrypted at rest:

```bash
docker compose exec db psql -U postgres -d github_agent \
  -c "select token_type, github_login, left(access_token_enc, 40) from github_credentials;"
```

You should see `gAAAAA...`, not your token.

---

Two things about working this way. `scripts/live_check.py` runs steps 4–10 in one pass and is stdlib-only, so your Mac's system `python3` runs it with no install: `python3 scripts/live_check.py --token ghp_xxx --repo ilia/agent-scratch`.

And the code is baked into the image, not bind-mounted — so **every code edit needs `docker compose --profile app up --build` again**. That rebuild cycle is exactly why I'd still develop against `docker compose up -d db` with the app on your own Python, and keep the full-container path for verifying it deploys. If you want live reload in the container, say so and I'll add a dev override with a volume mount.
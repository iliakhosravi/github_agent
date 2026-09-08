Here's the full walkthrough. Your folder is already a git repo but has no `.env` or virtualenv yet, so start at step 1.

## Before you start

You'll need a GitHub personal access token and an OpenAI key. For the token, go to GitHub → Settings → Developer settings → Personal access tokens. A **fine-grained** token needs *Contents: read & write*, *Pull requests: read & write*, and *Metadata: read* on the repos you'll test against; a **classic** token just needs the `repo` scope.

Also create a throwaway repo to test against — say `ilia/agent-scratch`, with a README in it so there's something to read. Don't point the write test at anything you care about.

## 1. Install

```bash
cd /Users/ilia/Projects/github_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Open `.env` and set three things — the key you just printed as `TOKEN_ENCRYPTION_KEY`, your `OPENAI_API_KEY`, and any random string as `SECRET_KEY`. Leave the rest alone for now.

Set one more, deliberately, for the first pass:

```
GITHUB_MCP_READONLY=true
```

This makes GitHub's MCP server reject every write. You'll confirm auth and connectivity can't damage anything, then turn it off at step 10.

## 3. Start Postgres

```bash
docker compose up -d db
docker compose ps        # should show healthy
```

## 4. Create the tables

```bash
export FLASK_APP=run.py
flask init-db            # → "Tables created."
```

## 5. Offline tests

```bash
pytest -q                # → 9 passed
```

If this fails, something's wrong with the install, not your config — nothing here touches GitHub or the LLM.

## 6. Boot it

```bash
python run.py
```

Leave it running and open a second terminal for everything below.

```bash
curl -s localhost:5000/api/health | python3 -m json.tool
```

You want `"database": true`. If it's false, Postgres isn't reachable — check step 3.

## 7. Store your token

```bash
curl -X POST localhost:5000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","token":"ghp_YOUR_TOKEN","default_repo":"ilia/agent-scratch"}'
```

A success returns your GitHub login — that's the service having called `GET /user` with your token to verify it. If you get `401 invalid_token`, the token is wrong or lacks scope; nothing was stored.

Confirm it persisted:

```bash
curl -s "localhost:5000/auth/status?user_id=ilia" | python3 -m json.tool
```

## 8. Check the MCP connection — the important one

```bash
curl -s "localhost:5000/api/tools?user_id=ilia" | python3 -m json.tool
```

This opens a real MCP session with your token and lists what came back. **It doesn't involve the LLM at all**, so it cleanly separates "GitHub/MCP is broken" from "the model isn't behaving." You should see a few dozen tools — `get_file_contents`, `create_branch`, `create_pull_request`, and so on.

If this fails, stop and fix it here. Nothing downstream can work.

## 9. A read-only agent turn

```bash
curl -X POST localhost:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","repo":"ilia/agent-scratch",
       "message":"List the files in the root of this repo and tell me what it contains."}'
```

Look at three things in the response: `reply` should describe your actual repo (if it's vague or generic, the model didn't really call tools), `tool_calls` should be non-empty, and `session_id` — copy it for the next step.

## 10. Does it remember

```bash
curl -X POST localhost:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","session_id":"PASTE_ID",
       "message":"What did I just ask you?"}'
```

Check `history_used` in the response — it should be greater than zero, and the reply should refer back to step 9. That's the 3-message window working.

## 11. A real change

Now turn off read-only. In `.env` set `GITHUB_MCP_READONLY=false`, then restart the server (Ctrl-C, `python run.py`).

```bash
curl -X POST localhost:5000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"ilia","repo":"ilia/agent-scratch",
       "message":"Add a file HELLO.md at the repo root with one line saying hello, and open a pull request for it."}'
```

Then check GitHub. You should see a new branch and an open PR — **not** a commit on `main`. If you find a commit directly on the default branch, the branch-and-PR instruction isn't holding and that's worth telling me about.

## 12. Check what got stored

```bash
curl -s "localhost:5000/api/sessions?user_id=ilia" | python3 -m json.tool
curl -s "localhost:5000/api/sessions/PASTE_ID/messages?user_id=ilia" | python3 -m json.tool
```

Every turn should be there with its tool calls — the full transcript, not just the 3-message window the model sees.

And if you want to confirm the tokens really are encrypted on disk:

```bash
docker compose exec db psql -U postgres -d github_agent \
  -c "select token_type, github_login, left(access_token_enc, 40) from github_credentials;"
```

You should see `gAAAAA...` ciphertext, not your token.

---

If you'd rather not type all of that, `python scripts/live_check.py --token ghp_xxx --repo ilia/agent-scratch` runs steps 6 through 12 in one go and stops at the first failure with the reason. The manual path above is better the first time, though — you see exactly where it breaks.
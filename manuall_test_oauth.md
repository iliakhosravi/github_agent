# Manual Test: GitHub OAuth

This walkthrough tests the GitHub OAuth flow in this project end to end:

1. redirect to GitHub,
2. callback back into Flask,
3. encrypted token storage,
4. authenticated GitHub MCP access,
5. one read-only agent request.

Use a throwaway GitHub repository for the final chat test, for example
`ilia/agent-scratch`.

## 1. Create a GitHub OAuth App

Open GitHub:

`Settings -> Developer settings -> OAuth Apps -> New OAuth App`

Choose the values based on how you run the app.

If you run the app directly with `python run.py`, use port `5000`:

```text
Application name: GitHub Agent Local
Homepage URL: http://127.0.0.1:5000
Authorization callback URL: http://127.0.0.1:5000/auth/github/callback
```

If you run the app with Docker Compose using `docker compose --profile app up`,
use port `5001`, because compose maps host `5001` to container `5000`:

```text
Application name: GitHub Agent Docker
Homepage URL: http://127.0.0.1:5001
Authorization callback URL: http://127.0.0.1:5001/auth/github/callback
```

After creating the app, copy:

- `Client ID`
- `Client secret`

The callback URL must match your `.env` value exactly. If you use `localhost`
in GitHub but `127.0.0.1` in `.env`, treat that as a mismatch. If you use
Docker Compose, use `5001` in both GitHub and `.env`.

## 2. Configure `.env`

From the project root:

```bash
cd /Users/ilia/Projects/github_agent
cp .env.example .env
```

Generate a token encryption key:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Edit `.env` and set at least these values:

```env
SECRET_KEY=any-long-random-string
TOKEN_ENCRYPTION_KEY=<the Fernet key you generated>

GITHUB_CLIENT_ID=<your GitHub OAuth app client id>
GITHUB_CLIENT_SECRET=<your GitHub OAuth app client secret>
# Local Python:
GITHUB_OAUTH_REDIRECT_URI=http://127.0.0.1:5000/auth/github/callback
# Docker Compose:
# GITHUB_OAUTH_REDIRECT_URI=http://127.0.0.1:5001/auth/github/callback
GITHUB_OAUTH_SCOPES=repo read:user

OPENAI_API_KEY=<your OpenAI key>
GITHUB_MCP_READONLY=true
```

Keep `GITHUB_MCP_READONLY=true` for the first OAuth test. It lets you verify
auth and MCP access without allowing writes.

## 3. Start the Database

```bash
docker compose up -d db
docker compose ps
```

The `db` service should become healthy.

## 4. Create Tables

```bash
export FLASK_APP=run.py
flask init-db
```

Expected result:

```text
Tables created.
```

## 5. Start the App

For local Python:

```bash
python run.py
```

The app is available at `http://127.0.0.1:5000`.

For Docker Compose:

```bash
docker compose --profile app up --build
```

The app is available at `http://127.0.0.1:5001` because
`docker-compose.yml` has this mapping:

```text
5001:5000
```

Leave this terminal running. Open a second terminal for the test commands. Set
`BASE_URL` to the URL that matches how you started the app:

```bash
# local Python
export BASE_URL=http://127.0.0.1:5000

# Docker Compose
export BASE_URL=http://127.0.0.1:5001
```

Check health:

```bash
curl -s "$BASE_URL/api/health" | python3 -m json.tool
```

You want:

```json
"database": true
```

## 6. Start OAuth in the Browser

Open this URL in your browser:

```text
$BASE_URL/auth/github/login?user_id=ilia
```

For Docker Compose, that means:

```text
http://127.0.0.1:5001/auth/github/login?user_id=ilia
```

Expected behavior:

1. The app redirects you to GitHub.
2. GitHub shows the OAuth authorization screen.
3. Approve the app.
4. GitHub redirects back to:

```text
$BASE_URL/auth/github/callback?code=...&state=...
```

If successful, the browser should show JSON similar to:

```json
{
  "credential": {
    "github_login": "your-github-login",
    "revoked": false,
    "scope": "repo,read:user",
    "token_type": "oauth"
  },
  "status": "connected",
  "user_id": "ilia"
}
```

The exact `scope` formatting may vary.

## 7. Confirm OAuth Token Was Stored

```bash
curl -s "$BASE_URL/auth/status?user_id=ilia" | python3 -m json.tool
```

Expected:

```json
{
  "connected": true,
  "credential": {
    "token_type": "oauth",
    "github_login": "your-github-login",
    "revoked": false
  },
  "user_id": "ilia"
}
```

The important parts are:

- `connected` is `true`
- `token_type` is `oauth`
- `github_login` is your GitHub username

## 8. Confirm the Token Is Encrypted in the Database

```bash
docker compose exec db psql -U postgres -d github_agent \
  -c "select token_type, github_login, left(access_token_enc, 40) from github_credentials;"
```

Expected:

```text
 token_type | github_login | left
------------+--------------+------------------------------------------
 oauth      | ...          | gAAAAA...
```

You should not see a raw GitHub token.

## 9. Test GitHub MCP Access

```bash
curl -s "$BASE_URL/api/tools?user_id=ilia" | python3 -m json.tool
```

Expected:

- The request returns `tools`.
- You should see GitHub-related tools such as repository, file, issue, branch,
  or pull request tools.

This step does not use the LLM. If this fails, OAuth token storage or GitHub MCP
access is broken, and `/api/chat` will not work either.

## 10. Test a Read-Only Agent Request

Use a repository your OAuth token can access:

```bash
curl -X POST "$BASE_URL/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{
        "user_id": "ilia",
        "repo": "ilia/agent-scratch",
        "message": "List the files in the root of this repository and tell me what it contains. Do not change anything."
      }'
```

Expected:

- `reply` describes your real repository.
- `tool_calls` is not empty.
- `repo` equals the repository you sent.
- `history_used` is usually `0` on the first request.

Because `GITHUB_MCP_READONLY=true`, write tools should be rejected if the model
tries to change anything.

## 11. Optional: Test the Browser Redirect with `next`

The login route supports a `next` query parameter. After a successful callback,
the app redirects there instead of returning JSON.

Example:

```text
$BASE_URL/auth/github/login?user_id=ilia&next=$BASE_URL/
```

After approving GitHub, you should land on `/`.

## 12. Optional: Revoke the Stored Credential

This deletes the stored credential from your local database:

```bash
curl -X DELETE "$BASE_URL/auth/token?user_id=ilia" | python3 -m json.tool
```

Expected:

```json
{
  "status": "revoked",
  "user_id": "ilia"
}
```

Then confirm:

```bash
curl -s "$BASE_URL/auth/status?user_id=ilia" | python3 -m json.tool
```

Expected:

```json
{
  "connected": false,
  "user_id": "ilia"
}
```

## Common Failures

### `github_oauth_is_not_configured`

Cause: `GITHUB_CLIENT_ID` or `GITHUB_CLIENT_SECRET` is empty.

Fix: Put both values in `.env`, then restart the app.

### `bad_state` or `The authorization request expired`

Cause: the `state` value is invalid, expired, or generated with a different
`SECRET_KEY`.

Fix: start again from:

```text
$BASE_URL/auth/github/login?user_id=ilia
```

Do not reuse old callback URLs.

### GitHub says callback URL mismatch

Cause: GitHub OAuth App callback URL and `GITHUB_OAUTH_REDIRECT_URI` do not
match exactly.

Fix both to the callback URL for the way you run the app:

```text
# local Python
http://127.0.0.1:5000/auth/github/callback

# Docker Compose
http://127.0.0.1:5001/auth/github/callback
```

### `/api/tools` fails after OAuth succeeds

OAuth worked, but the token cannot access GitHub MCP properly.

Check:

- `GITHUB_OAUTH_SCOPES=repo read:user`
- you approved the app with the right GitHub account
- the repo is accessible by that account
- the app was restarted after `.env` changes

### `/api/chat` says no token is stored

Cause: you used a different `user_id` between OAuth and chat.

Fix: use the same value everywhere, for example:

```text
user_id=ilia
```

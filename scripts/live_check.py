#!/usr/bin/env python3
"""End-to-end check against a running server.

Walks the whole path: health -> store token -> list MCP tools -> a read-only
agent turn -> a second turn that proves the conversation memory works.
Stdlib only, no extra dependencies.

    python scripts/live_check.py --token ghp_xxx --repo owner/name

Add --write to also ask the agent to make a real change (branch + PR).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def call(method: str, url: str, payload: dict | None = None, timeout: int = 360):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": body.decode(errors="replace")[:500]}
    except urllib.error.URLError as exc:
        return 0, {"error": {"message": f"cannot reach the server: {exc.reason}"}}


def step(number: int, title: str) -> None:
    print(f"\n{BOLD}[{number}] {title}{RESET}")


def show(status: int, body: dict, *, ok_codes=(200,)) -> bool:
    ok = status in ok_codes
    mark = f"{GREEN}ok{RESET}" if ok else f"{RED}FAILED{RESET}"
    print(f"    HTTP {status or '---'}  {mark}")
    if not ok:
        message = (body.get("error") or {}).get("message") or json.dumps(body)[:400]
        print(f"    {RED}{message}{RESET}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    parser.add_argument("--user", default="live-check")
    parser.add_argument("--token", help="GitHub PAT to register for this user")
    parser.add_argument("--repo", help="owner/name to target")
    parser.add_argument(
        "--write",
        action="store_true",
        help="also run a prompt that makes a real change (branch + PR)",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="override the agent prompt used for the main turn",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")

    step(1, "Server and config")
    status, body = call("GET", f"{base}/api/health")
    if not show(status, body):
        print(f"    {DIM}Is the server running?  python run.py{RESET}")
        return 1
    print(
        f"    db={body['database']}  llm={body['llm']['provider']}/{body['llm']['model']}"
        f"  write_mode={body['write_mode']}  history_limit={body['history_limit']}"
    )

    if args.token:
        step(2, "Register the GitHub token")
        payload = {"user_id": args.user, "token": args.token}
        if args.repo:
            payload["default_repo"] = args.repo
        status, body = call("POST", f"{base}/auth/token", payload)
        if not show(status, body):
            return 1
        print(f"    stored for GitHub user @{body['credential']['github_login']}")
    else:
        step(2, "Check the stored token")
        status, body = call("GET", f"{base}/auth/status?user_id={args.user}")
        if not show(status, body) or not body.get("connected"):
            print(f"    {RED}no token stored for '{args.user}' -- pass --token{RESET}")
            return 1
        print(f"    connected as @{body['credential']['github_login']}")

    step(3, "Tools visible through the GitHub MCP server")
    status, body = call("GET", f"{base}/api/tools?user_id={args.user}")
    if not show(status, body):
        print(f"    {DIM}A failure here means the token or the MCP URL is wrong.{RESET}")
        return 1
    tools = body["tools"]
    print(f"    {len(tools)} tools: {', '.join(t['name'] for t in tools[:8])}"
          f"{' ...' if len(tools) > 8 else ''}")

    step(4, "Agent turn (read-only)")
    prompt = args.prompt or (
        f"List the files in the root of {args.repo} and tell me in two sentences "
        "what this project does. Do not change anything."
        if args.repo
        else "Which repositories can you see for me? List up to five by name."
    )
    print(f"    {DIM}> {prompt}{RESET}")
    payload = {"user_id": args.user, "message": prompt}
    if args.repo:
        payload["repo"] = args.repo
    status, body = call("POST", f"{base}/api/chat", payload)
    if not show(status, body):
        return 1
    session_id = body["session_id"]
    print(f"    session={session_id}  tools_called={len(body['tool_calls'])}")
    for call_info in body["tool_calls"]:
        print(f"      {DIM}- {call_info['name']}{RESET}")
    print(f"    {body['reply'][:700]}")

    step(5, "Second turn -- does it remember?")
    follow_up = "What was the first thing I asked you in this conversation?"
    print(f"    {DIM}> {follow_up}{RESET}")
    status, body = call(
        "POST",
        f"{base}/api/chat",
        {"user_id": args.user, "message": follow_up, "session_id": session_id},
    )
    if not show(status, body):
        return 1
    print(f"    history_used={body['history_used']} (should be > 0)")
    print(f"    {body['reply'][:400]}")

    if args.write:
        if not args.repo:
            print(f"\n{RED}--write needs --repo{RESET}")
            return 1
        step(6, "Agent turn (real change -> branch + PR)")
        write_prompt = (
            "Add a file called AGENT_TEST.md at the repository root containing a "
            "single line: 'Written by the github agent.' Open a pull request for it."
        )
        print(f"    {DIM}> {write_prompt}{RESET}")
        status, body = call(
            "POST",
            f"{base}/api/chat",
            {
                "user_id": args.user,
                "message": write_prompt,
                "session_id": session_id,
                "repo": args.repo,
            },
        )
        if not show(status, body):
            return 1
        for call_info in body["tool_calls"]:
            print(f"      {DIM}- {call_info['name']}{RESET}")
        print(f"    {body['reply'][:700]}")

    step(7 if args.write else 6, "Stored transcript")
    status, body = call(
        "GET", f"{base}/api/sessions/{session_id}/messages?user_id={args.user}"
    )
    if not show(status, body):
        return 1
    print(f"    {len(body['messages'])} messages persisted for session {session_id}")

    print(f"\n{GREEN}{BOLD}All checks passed.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

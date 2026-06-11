from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AuthCommand:
    provider: str
    label: str
    login_command: str
    status_command: list[str] | None = None
    credential_path: Path | None = None


@dataclass
class AuthLaunchResult:
    ok: bool
    message: str
    command: str
    terminal: str | None = None


PROVIDER_AUTH: dict[str, AuthCommand] = {
    "codex": AuthCommand(
        provider="codex",
        label="Codex",
        login_command="codex login",
        credential_path=Path.home() / ".codex" / "auth.json",
    ),
    "claude": AuthCommand(
        provider="claude",
        label="Claude",
        login_command="claude auth login",
        status_command=["claude", "auth", "status"],
        credential_path=Path.home() / ".claude" / ".credentials.json",
    ),
}


def provider_auth(provider: str) -> AuthCommand | None:
    return PROVIDER_AUTH.get(provider)


def provider_login_command(provider: str) -> str | None:
    auth = provider_auth(provider)
    return auth.login_command if auth else None


def _terminal_script(auth: AuthCommand) -> str:
    return "\n".join([
        "set +e",
        f"echo 'TokenBar: signing in to {auth.label}'",
        f"{auth.login_command}",
        "status=$?",
        "echo",
        "if [ $status -eq 0 ]; then echo 'TokenBar: auth command finished.'; else echo \"TokenBar: auth command failed with exit $status.\"; fi",
        "echo 'You can close this terminal after reviewing the result.'",
        "read -r -p 'Press Enter to close...' _",
        "exit $status",
    ])


def terminal_launch_candidates(script: str) -> list[tuple[str, list[str]]]:
    return [
        ("xdg-terminal-exec", ["xdg-terminal-exec", "bash", "-lc", script]),
        ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", script]),
        ("kgx", ["kgx", "--", "bash", "-lc", script]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-lc", script]),
    ]


def launch_interactive_auth(provider: str) -> AuthLaunchResult:
    auth = provider_auth(provider)
    if auth is None:
        return AuthLaunchResult(False, f"Unsupported provider: {provider}", "")

    script = _terminal_script(auth)
    for name, command in terminal_launch_candidates(script):
        if shutil.which(name) is None:
            continue
        try:
            subprocess.Popen(command)
            return AuthLaunchResult(True, f"Opened terminal for {auth.label} sign-in.", auth.login_command, name)
        except Exception as exc:
            last_error = f"{name}: {type(exc).__name__}: {exc}"
            continue

    detail = locals().get("last_error", "no supported graphical terminal found")
    return AuthLaunchResult(False, f"Could not open a terminal for {auth.label}: {detail}", auth.login_command)


def auth_status(provider: str) -> tuple[bool, str]:
    auth = provider_auth(provider)
    if auth is None:
        return False, f"Unsupported provider: {provider}"

    if auth.status_command and shutil.which(auth.status_command[0]):
        try:
            result = subprocess.run(auth.status_command, capture_output=True, text=True, timeout=10)
        except Exception as exc:
            return False, f"{auth.label}: status failed ({type(exc).__name__}: {exc})"
        if result.returncode == 0:
            summary = _summarize_status_output(result.stdout.strip())
            return True, f"{auth.label}: signed in" + (f" · {summary}" if summary else "")
        detail = (result.stderr or result.stdout).strip()
        return False, f"{auth.label}: not signed in" + (f" · {detail}" if detail else "")

    if auth.credential_path and auth.credential_path.exists():
        return True, f"{auth.label}: credentials found at {auth.credential_path}"
    return False, f"{auth.label}: not signed in"


def all_auth_status() -> list[tuple[str, bool, str]]:
    return [(provider, *auth_status(provider)) for provider in PROVIDER_AUTH]


def _summarize_status_output(output: str) -> str:
    if not output:
        return ""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return output.splitlines()[0][:120]
    parts = []
    email = data.get("email")
    subscription = data.get("subscriptionType") or data.get("authMethod")
    if email:
        parts.append(str(email))
    if subscription:
        parts.append(str(subscription))
    return " · ".join(parts)

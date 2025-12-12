#!/usr/bin/env python3
"""Check name availability across multiple platforms."""

import argparse
import asyncio
import os
import re
import subprocess
import sys

import httpx
from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_TLDS = ["com", "io", "org", "dev", "ai"]
TIMEOUT = 10.0

# GitHub token (resolved once at startup)
_github_token: str | None = None


def get_github_token() -> str | None:
    """Get GitHub token from env var or gh CLI."""
    global _github_token
    if _github_token is not None:
        return _github_token if _github_token else None

    # Try GITHUB_TOKEN env var first
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        _github_token = token
        return token

    # Try gh CLI
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            _github_token = result.stdout.strip()
            return _github_token
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    _github_token = ""  # Mark as checked but not found
    return None


def get_github_headers() -> dict:
    """Get headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github+json"}
    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def normalize_pypi_name(name: str) -> str:
    """Normalize package name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


async def check_comfy_publisher(client: httpx.AsyncClient, name: str) -> dict:
    """Check Comfy Registry publisher name availability."""
    try:
        r = await client.get(
            "https://api.comfy.org/publishers/validate",
            params={"username": name},
        )
        if r.status_code == 200:
            data = r.json()
            available = data.get("isAvailable", False)
            return {"available": available, "detail": "" if available else "taken"}
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": None, "detail": str(e)}


async def check_comfy_node(client: httpx.AsyncClient, name: str) -> dict:
    """Check if a node with this name exists in Comfy Registry."""
    try:
        r = await client.get(
            "https://api.comfy.org/nodes/search",
            params={"search": name, "limit": 5},
        )
        if r.status_code == 200:
            data = r.json()
            nodes = data.get("nodes", [])
            # Check for exact match
            exact = [n for n in nodes if n.get("id", "").lower() == name.lower()]
            if exact:
                publisher = exact[0].get("publisher", {}).get("id", "unknown")
                return {"available": False, "detail": f"by @{publisher}"}
            return {"available": True, "detail": ""}
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": None, "detail": str(e)}


async def check_pypi(client: httpx.AsyncClient, name: str) -> dict:
    """Check PyPI package availability (checks normalized name)."""
    normalized = normalize_pypi_name(name)
    try:
        r = await client.get(f"https://pypi.org/pypi/{normalized}/json")
        if r.status_code == 404:
            return {"available": True, "detail": ""}
        if r.status_code == 200:
            return {"available": False, "detail": f"(normalized: {normalized})" if normalized != name else ""}
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": None, "detail": str(e)}


async def check_npm(client: httpx.AsyncClient, name: str) -> dict:
    """Check npm package availability."""
    try:
        r = await client.get(f"https://registry.npmjs.org/{name}")
        if r.status_code == 404:
            return {"available": True, "detail": ""}
        if r.status_code == 200:
            return {"available": False, "detail": ""}
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": None, "detail": str(e)}


async def check_github_user(client: httpx.AsyncClient, name: str, headers: dict) -> dict:
    """Check GitHub username availability."""
    try:
        r = await client.get(f"https://api.github.com/users/{name}", headers=headers)
        if r.status_code == 404:
            return {"available": True, "detail": ""}
        if r.status_code == 200:
            data = r.json()
            user_type = data.get("type", "User")
            return {"available": False, "detail": user_type}
        if r.status_code == 403:
            return {"available": None, "detail": "rate limited"}
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": None, "detail": str(e)}


async def check_github_org(client: httpx.AsyncClient, name: str, headers: dict) -> dict:
    """Check GitHub organization availability."""
    try:
        r = await client.get(f"https://api.github.com/orgs/{name}", headers=headers)
        if r.status_code == 404:
            return {"available": True, "detail": ""}
        if r.status_code == 200:
            data = r.json()
            repos = data.get("public_repos", 0)
            return {"available": False, "detail": f"{repos} repos"}
        if r.status_code == 403:
            return {"available": None, "detail": "rate limited"}
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": None, "detail": str(e)}


async def check_domain(client: httpx.AsyncClient, name: str, tld: str) -> dict:
    """Check domain availability via RDAP."""
    domain = f"{name}.{tld}"
    try:
        r = await client.get(f"https://rdap.org/domain/{domain}", follow_redirects=True)
        # 404 means not found = available
        if r.status_code == 404:
            return {"available": True, "detail": ""}
        if r.status_code == 200:
            try:
                data = r.json()
                # Check for RDAP error response (some registries return 200 with error object)
                if "errorCode" in data:
                    return {"available": True, "detail": ""}
                # Valid domain record - extract expiration
                events = data.get("events", [])
                expiry = next(
                    (e.get("eventDate", "")[:10] for e in events if e.get("eventAction") == "expiration"),
                    None,
                )
                detail = f"exp {expiry}" if expiry else ""
                return {"available": False, "detail": detail}
            except Exception:
                # Non-JSON response or parse error
                return {"available": None, "detail": "parse error"}
        # Other status codes
        return {"available": None, "detail": f"HTTP {r.status_code}"}
    except httpx.TimeoutException:
        return {"available": None, "detail": "timeout"}
    except Exception as e:
        return {"available": None, "detail": str(e)[:30]}


async def run_checks(name: str, tlds: list[str], skip: set[str]) -> list[tuple[str, dict]]:
    """Run all availability checks in parallel."""
    results = []
    github_headers = get_github_headers()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        tasks = []
        labels = []

        if "comfy" not in skip:
            tasks.append(check_comfy_publisher(client, name))
            labels.append("Comfy Publisher")
            tasks.append(check_comfy_node(client, name))
            labels.append("Comfy Node")

        if "pypi" not in skip:
            tasks.append(check_pypi(client, name))
            labels.append("PyPI")

        if "npm" not in skip:
            tasks.append(check_npm(client, name))
            labels.append("npm")

        if "github" not in skip:
            tasks.append(check_github_user(client, name, github_headers))
            labels.append("GitHub User")
            tasks.append(check_github_org(client, name, github_headers))
            labels.append("GitHub Org")

        if "domain" not in skip:
            for tld in tlds:
                tasks.append(check_domain(client, name, tld))
                labels.append(f"{name}.{tld}")

        responses = await asyncio.gather(*tasks)
        results = list(zip(labels, responses))

    return results


def format_status(result: dict) -> str:
    """Format availability status with colors."""
    if result["available"] is True:
        return "[green]✓ Available[/green]"
    elif result["available"] is False:
        return "[red]✗ Taken[/red]"
    else:
        return "[yellow]? Unknown[/yellow]"


def check_single_name(name: str, tlds: list[str], skip: set[str]) -> None:
    """Check and display results for a single name."""
    console.print(f"\nChecking availability for: [bold]{name}[/bold]\n")

    results = asyncio.run(run_checks(name, tlds, skip))

    # Check for rate limit warnings
    rate_limited = [label for label, r in results if r.get("detail") == "rate limited"]
    if rate_limited:
        console.print(f"[yellow]⚠ Rate limited on: {', '.join(rate_limited)}[/yellow]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Platform", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    for label, result in results:
        table.add_row(label, format_status(result), result.get("detail", ""))

    console.print(table)

    # Summary
    available = sum(1 for _, r in results if r["available"] is True)
    taken = sum(1 for _, r in results if r["available"] is False)
    unknown = sum(1 for _, r in results if r["available"] is None)

    console.print(f"\n[green]{available} available[/green] | [red]{taken} taken[/red] | [yellow]{unknown} unknown[/yellow]\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check name availability across Comfy Registry, PyPI, GitHub, npm, and domains"
    )
    parser.add_argument("names", help="Name(s) to check (comma-separated for multiple)")
    parser.add_argument("--tlds", default=",".join(DEFAULT_TLDS), help=f"Comma-separated TLDs (default: {','.join(DEFAULT_TLDS)})")
    parser.add_argument("--skip", default="", help="Skip checks: comfy,pypi,npm,github,domain")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    args = parser.parse_args()

    tlds = [t.strip().lstrip(".") for t in args.tlds.split(",") if t.strip()]
    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()}
    names = [n.strip() for n in args.names.split(",") if n.strip()]

    for name in names:
        check_single_name(name, tlds, skip)
        if name != names[-1]:
            console.rule()

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Atomic GitHub repository sync for auto-saving custom researched trips to gfinley/adventure-advisor."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


def _repo_config() -> tuple[str, str, str]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPO", "gfinley/adventure-advisor").strip()
    branch = os.getenv("GITHUB_BRANCH", "main").strip()
    return token, repo, branch


def is_github_sync_enabled() -> bool:
    token, repo, _ = _repo_config()
    return bool(token and repo)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _fetch_json_file(
    client: httpx.AsyncClient, repo: str, path: str, branch: str
) -> Any:
    r = await client.get(f"{GITHUB_API}/repos/{repo}/contents/{path}", params={"ref": branch})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    raw = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(raw)


async def _atomic_commit_files(
    client: httpx.AsyncClient,
    repo: str,
    branch: str,
    files: dict[str, str],
    commit_message: str,
) -> dict[str, str]:
    """Commit multiple JSON files atomically to branch via GitHub Git Data API."""
    # 1. Get HEAD commit SHA
    ref_resp = await client.get(f"{GITHUB_API}/repos/{repo}/git/ref/heads/{branch}")
    ref_resp.raise_for_status()
    head_sha = ref_resp.json()["object"]["sha"]

    # 2. Get base tree SHA
    commit_resp = await client.get(f"{GITHUB_API}/repos/{repo}/git/commits/{head_sha}")
    commit_resp.raise_for_status()
    base_tree_sha = commit_resp.json()["tree"]["sha"]

    # 3. Create blobs for each updated file
    tree_entries = []
    for path, content_str in files.items():
        blob_resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/git/blobs",
            json={"content": content_str, "encoding": "utf-8"},
        )
        blob_resp.raise_for_status()
        tree_entries.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_resp.json()["sha"],
        })

    # 4. Create new tree
    new_tree_resp = await client.post(
        f"{GITHUB_API}/repos/{repo}/git/trees",
        json={"base_tree": base_tree_sha, "tree": tree_entries},
    )
    new_tree_resp.raise_for_status()
    new_tree_sha = new_tree_resp.json()["sha"]

    # 5. Create new commit
    new_commit_resp = await client.post(
        f"{GITHUB_API}/repos/{repo}/git/commits",
        json={
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [head_sha],
        },
    )
    new_commit_resp.raise_for_status()
    new_commit_sha = new_commit_resp.json()["sha"]

    # 6. Move branch ref forward
    patch_resp = await client.patch(
        f"{GITHUB_API}/repos/{repo}/git/refs/heads/{branch}",
        json={"sha": new_commit_sha, "force": False},
    )
    patch_resp.raise_for_status()

    return {
        "commitSha": new_commit_sha[:7],
        "commitUrl": f"https://github.com/{repo}/commit/{new_commit_sha}",
    }


def _recompute_meta(dataset: dict[str, Any], custom_count: int) -> None:
    months = dataset.get("months", [])
    total = sum(len(m.get("adventures", [])) for m in months)
    nordic = sum(
        1 for m in months for a in m.get("adventures", []) if a.get("isNordic", False)
    )
    meta = dataset.setdefault("meta", {})
    meta["generatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["adventureCount"] = total
    meta["nordicCount"] = nordic
    meta["customResearchCount"] = custom_count


async def save_custom_adventure_to_github(
    month_id: str, adventure: dict[str, Any], prompt: str
) -> dict[str, Any]:
    """Append adventure to data/custom.json and data/adventures.json in one atomic commit."""
    token, repo, branch = _repo_config()
    if not token:
        return {"saved": False, "reason": "GITHUB_TOKEN not configured"}

    async with httpx.AsyncClient(headers=_headers(token), timeout=30.0) as client:
        custom_list = await _fetch_json_file(client, repo, "data/custom.json", branch)
        if not isinstance(custom_list, list):
            custom_list = []

        dataset = await _fetch_json_file(client, repo, "data/adventures.json", branch)
        if not isinstance(dataset, dict) or "months" not in dataset:
            raise RuntimeError("data/adventures.json missing or invalid in repository")

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        custom_list.insert(
            0,
            {
                "monthId": month_id,
                "prompt": prompt,
                "createdAt": now_iso,
                "adventure": adventure,
            },
        )

        # Insert into matching month inside adventures.json
        target_month = next(
            (m for m in dataset["months"] if m.get("monthId") == month_id),
            dataset["months"][0],
        )
        # Avoid duplicates if retried
        target_month["adventures"] = [
            a for a in target_month["adventures"] if a.get("id") != adventure["id"]
        ]
        target_month["adventures"].insert(0, adventure)
        _recompute_meta(dataset, len(custom_list))

        commit_info = await _atomic_commit_files(
            client,
            repo,
            branch,
            files={
                "data/custom.json": json.dumps(custom_list, indent=2, ensure_ascii=False) + "\n",
                "data/adventures.json": json.dumps(dataset, indent=2, ensure_ascii=False) + "\n",
            },
            commit_message=f"Agent research ({month_id}): {adventure['title'][:64]}",
        )
        return {"saved": True, **commit_info}


async def delete_custom_adventure_from_github(adv_id: str) -> dict[str, Any]:
    """Remove a custom researched adventure from data/custom.json and data/adventures.json."""
    token, repo, branch = _repo_config()
    if not token:
        raise RuntimeError("GITHUB_TOKEN not configured")

    async with httpx.AsyncClient(headers=_headers(token), timeout=30.0) as client:
        custom_list = await _fetch_json_file(client, repo, "data/custom.json", branch) or []
        dataset = await _fetch_json_file(client, repo, "data/adventures.json", branch)
        if not isinstance(dataset, dict):
            raise RuntimeError("data/adventures.json missing")

        before = len(custom_list)
        custom_list = [
            item for item in custom_list
            if item.get("adventure", {}).get("id") != adv_id
        ]
        for month in dataset.get("months", []):
            month["adventures"] = [
                a for a in month.get("adventures", []) if a.get("id") != adv_id
            ]

        if len(custom_list) == before:
            return {"deleted": False, "reason": "Adventure ID not found in custom.json"}

        _recompute_meta(dataset, len(custom_list))
        commit_info = await _atomic_commit_files(
            client,
            repo,
            branch,
            files={
                "data/custom.json": json.dumps(custom_list, indent=2, ensure_ascii=False) + "\n",
                "data/adventures.json": json.dumps(dataset, indent=2, ensure_ascii=False) + "\n",
            },
            commit_message=f"Remove custom researched adventure: {adv_id}",
        )
        return {"deleted": True, **commit_info}

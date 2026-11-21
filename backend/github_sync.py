"""Atomic GitHub repository sync for auto-saving custom trips into AES-256-GCM encrypted data/adventures.enc.json."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

GITHUB_API = "https://api.github.com"
PBKDF2_ITERATIONS = 210_000


def _repo_config() -> tuple[str, str, str, str]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPO", "gfinley/adventure-advisor").strip()
    branch = os.getenv("GITHUB_BRANCH", "main").strip()
    vault_pass = os.getenv("SITE_VAULT_PASSPHRASE", "").strip()
    return token, repo, branch, vault_pass


def is_github_sync_enabled() -> bool:
    token, repo, _, vault_pass = _repo_config()
    return bool(token and repo and vault_pass)


def _derive_key(passphrase: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def decrypt_vault(envelope: dict[str, Any], passphrase: str) -> Any:
    salt = base64.b64decode(envelope["salt"])
    iv = base64.b64decode(envelope["iv"])
    combined = base64.b64decode(envelope["ciphertext"])
    key = _derive_key(passphrase, salt, int(envelope.get("iterations", PBKDF2_ITERATIONS)))
    plaintext = AESGCM(key).decrypt(iv, combined, None)
    return json.loads(plaintext.decode("utf-8"))


def encrypt_vault(payload: Any, passphrase: str) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = _derive_key(passphrase, salt, PBKDF2_ITERATIONS)
    combined = AESGCM(key).encrypt(iv, raw, None)
    return {
        "version": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "cipher": "AES-256-GCM",
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(combined).decode("ascii"),
    }


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
    """Commit updated files atomically to branch via GitHub Git Data API."""
    ref_resp = await client.get(f"{GITHUB_API}/repos/{repo}/git/ref/heads/{branch}")
    ref_resp.raise_for_status()
    head_sha = ref_resp.json()["object"]["sha"]

    commit_resp = await client.get(f"{GITHUB_API}/repos/{repo}/git/commits/{head_sha}")
    commit_resp.raise_for_status()
    base_tree_sha = commit_resp.json()["tree"]["sha"]

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

    new_tree_resp = await client.post(
        f"{GITHUB_API}/repos/{repo}/git/trees",
        json={"base_tree": base_tree_sha, "tree": tree_entries},
    )
    new_tree_resp.raise_for_status()
    new_tree_sha = new_tree_resp.json()["sha"]

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

    patch_resp = await client.patch(
        f"{GITHUB_API}/repos/{repo}/git/refs/heads/{branch}",
        json={"sha": new_commit_sha, "force": False},
    )
    patch_resp.raise_for_status()

    return {
        "commitSha": new_commit_sha[:7],
        "commitUrl": f"https://github.com/{repo}/commit/{new_commit_sha}",
    }


def _recompute_meta(dataset: dict[str, Any]) -> None:
    months = dataset.get("months", [])
    all_advs = [a for m in months for a in m.get("adventures", [])]
    meta = dataset.setdefault("meta", {})
    meta["generatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["adventureCount"] = len(all_advs)
    meta["nordicCount"] = sum(1 for a in all_advs if a.get("isNordic", False))
    meta["customResearchCount"] = sum(1 for a in all_advs if a.get("isCustomResearch", False))


async def save_custom_adventure_to_github(
    month_id: str, adventure: dict[str, Any], prompt: str
) -> dict[str, Any]:
    """Decrypt data/adventures.enc.json, insert adventure, re-encrypt, and commit atomically."""
    token, repo, branch, vault_pass = _repo_config()
    if not token or not vault_pass:
        return {"saved": False, "reason": "GITHUB_TOKEN or SITE_VAULT_PASSPHRASE not configured"}

    async with httpx.AsyncClient(headers=_headers(token), timeout=30.0) as client:
        envelope = await _fetch_json_file(client, repo, "data/adventures.enc.json", branch)
        if not isinstance(envelope, dict) or "ciphertext" not in envelope:
            raise RuntimeError("data/adventures.enc.json missing or invalid in repository")

        dataset = decrypt_vault(envelope, vault_pass)
        target_month = next(
            (m for m in dataset["months"] if m.get("monthId") == month_id),
            dataset["months"][0],
        )
        target_month["adventures"] = [
            a for a in target_month["adventures"] if a.get("id") != adventure["id"]
        ]
        target_month["adventures"].insert(0, adventure)
        _recompute_meta(dataset)

        new_envelope = encrypt_vault(dataset, vault_pass)
        commit_info = await _atomic_commit_files(
            client,
            repo,
            branch,
            files={
                "data/adventures.enc.json": json.dumps(new_envelope) + "\n",
            },
            commit_message=f"Encrypted vault update ({month_id}): new agent-researched trip",
        )
        return {"saved": True, **commit_info}


async def delete_custom_adventure_from_github(adv_id: str) -> dict[str, Any]:
    """Decrypt data/adventures.enc.json, remove custom adventure, re-encrypt, and commit."""
    token, repo, branch, vault_pass = _repo_config()
    if not token or not vault_pass:
        raise RuntimeError("GITHUB_TOKEN or SITE_VAULT_PASSPHRASE not configured")

    async with httpx.AsyncClient(headers=_headers(token), timeout=30.0) as client:
        envelope = await _fetch_json_file(client, repo, "data/adventures.enc.json", branch)
        if not isinstance(envelope, dict):
            raise RuntimeError("data/adventures.enc.json missing")

        dataset = decrypt_vault(envelope, vault_pass)
        removed = False
        for month in dataset.get("months", []):
            before = len(month.get("adventures", []))
            month["adventures"] = [
                a for a in month.get("adventures", []) if a.get("id") != adv_id
            ]
            if len(month["adventures"]) < before:
                removed = True

        if not removed:
            return {"deleted": False, "reason": "Adventure ID not found"}

        _recompute_meta(dataset)
        new_envelope = encrypt_vault(dataset, vault_pass)
        commit_info = await _atomic_commit_files(
            client,
            repo,
            branch,
            files={
                "data/adventures.enc.json": json.dumps(new_envelope) + "\n",
            },
            commit_message="Encrypted vault update: removed custom researched trip",
        )
        return {"deleted": True, **commit_info}

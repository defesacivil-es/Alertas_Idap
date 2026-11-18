"""Persist generated state without force pushes or repeating Sheets writes."""

import json
import logging
import os
import subprocess
from pathlib import Path

from .sheets_registry import alert_key, load_pending, merge_pending, save_pending

FILES = (
    ".cache/state.json", ".cache/historico_alertas.json", ".cache/sheets_pending.json",
    "site/dashboard_data.json", "site/data/geojs-es.json",
    "site/data/alertas_idap.geojson", "site/ultima_atualizacao.json",
)
QUEUE = ".cache/sheets_pending.json"


def _git(repo: Path, *args: str, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError("Git state persistence failed: " + args[0])
    return result


def _remote_queue(repo: Path) -> list[dict]:
    raw = _git(repo, "show", f"origin/main:{QUEUE}", check=False)
    if raw.returncode:
        return []
    data = json.loads(raw.stdout)
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("alerts"), list)
            or any(not isinstance(a, dict) or not alert_key(a) for a in data["alerts"])):
        raise ValueError("Invalid remote pending queue")
    return data["alerts"]


def persist(repo: Path, attempts=3, before_push=None) -> None:
    if _git(repo, "branch", "--show-current").stdout.strip() != b"main":
        raise RuntimeError("State persistence is restricted to main")
    changed = set()
    for args in (("diff", "--name-only"), ("diff", "--cached", "--name-only")):
        changed.update(_git(repo, *args).stdout.decode().splitlines())
    if changed - set(FILES):
        raise RuntimeError("Refusing to commit unrelated tracked changes")
    existing = [p for p in FILES if (repo / p).is_file()]
    if existing:
        _git(repo, "add", "--", *existing)
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode:
        _git(repo, "commit", "-m", "Atualiza dashboards e fila Sheets [skip ci]")
    for attempt in range(attempts):
        if before_push:
            before_push(attempt)
        if _git(repo, "push", "origin", "HEAD:main", check=False).returncode == 0:
            return
        _git(repo, "fetch", "origin", "main")
        snapshots = {p: (repo / p).read_bytes() for p in FILES if (repo / p).is_file()}
        local_pending = load_pending(repo / QUEUE)
        remote_pending = _remote_queue(repo)
        merged = _git(repo, "merge", "--no-edit", "origin/main", check=False)
        conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.decode().splitlines()
        if any(p not in FILES or p not in snapshots for p in conflicts):
            # Leave code conflicts visible and preserve a usable queue for recovery.
            if local_pending or remote_pending:
                save_pending(repo / QUEUE, merge_pending(local_pending, remote_pending))
            raise RuntimeError("Code conflict: recover queue artifact and resolve manually")
        if merged.returncode and not conflicts:
            raise RuntimeError("Unable to integrate remote state")
        for path in conflicts:
            if path == QUEUE:
                continue
            if path == ".cache/historico_alertas.json":
                ours = json.loads(snapshots[path])
                theirs = json.loads(_git(repo, "show", f"origin/main:{path}").stdout)
                records = {}
                for record in [*theirs, *ours]:
                    key = record.get("entry_id") or record.get("identifier")
                    if key:
                        records[key] = record
                (repo / path).write_text(json.dumps(list(records.values()), ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                # Current run's generated view; never apply this rule to code.
                (repo / path).write_bytes(snapshots[path])
        if local_pending or remote_pending or QUEUE in snapshots:
            save_pending(repo / QUEUE, merge_pending(local_pending, remote_pending))
        existing = [p for p in FILES if (repo / p).is_file()]
        _git(repo, "add", "--", *existing)
        if conflicts or _git(repo, "diff", "--cached", "--quiet", check=False).returncode:
            _git(repo, "commit", "-m", "Integra estado remoto sem reenviar Sheets [skip ci]")
    raise RuntimeError("Push not confirmed after three attempts; recover workflow artifact")


def main() -> int:
    from .sync_alerts_sheets import require_production
    try:
        require_production()
        persist(Path.cwd())
        return 0
    except Exception as error:
        logging.error("State persistence failed (%s). Recover the queue artifact.", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

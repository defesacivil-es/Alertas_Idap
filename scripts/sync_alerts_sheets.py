"""Idempotent single-writer Sheets synchronization. Dry-run never authenticates."""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .sheets_registry import HEADERS, alert_key, load_pending, merge_pending, row_values, save_pending

LOG = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def require_production() -> None:
    if (os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_REPOSITORY", "").casefold() != "defesacivil-es/alertas_idap"):
        raise ValueError("Production Sheets writes require the expected repository and main ref")


def column_name(number: int) -> str:
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output


class SheetsClient:
    def __init__(self, session, spreadsheet_id: str, sheet_id: int):
        self.session = session
        self.base = "https://sheets.googleapis.com/v4/spreadsheets/" + quote(spreadsheet_id, safe="")
        metadata = self._request("GET", self.base, params={"fields": "sheets.properties"})
        sheet = next((s["properties"] for s in metadata["sheets"]
                      if s["properties"]["sheetId"] == sheet_id), None)
        if sheet is None:
            raise ValueError("Configured sheetId not found")
        self.sheet = sheet

    def _request(self, method, url, **kwargs):
        response = self.session.request(method, url, timeout=45, **kwargs)
        response.raise_for_status()
        return response.json()

    def _range_url(self, coordinates):
        title = self.sheet["title"].replace("'", "''")
        return self.base + "/values/" + quote(f"'{title}'!{coordinates}", safe="")

    def read_rows(self) -> list[list[str]]:
        grid = self.sheet["gridProperties"]
        last_column = column_name(grid["columnCount"])
        rows = []
        # Include all allocated columns when checking emptiness, not just A:L.
        for start in range(1, grid["rowCount"] + 1, 1000):
            end = min(start + 999, grid["rowCount"])
            data = self._request("GET", self._range_url(f"A{start}:{last_column}{end}"),
                                 params={"valueRenderOption": "FORMATTED_VALUE"})
            page = data.get("values", [])
            rows.extend(page)
            if end != grid["rowCount"]:
                rows.extend([[] for _ in range(end - start + 1 - len(page))])
        while rows and not any(rows[-1]):
            rows.pop()
        return rows

    def initialize_headers(self) -> None:
        self._request("PUT", self._range_url("A1:L1"),
                      params={"valueInputOption": "RAW"}, json={"values": [list(HEADERS)]})

    def append_rows(self, rows: list[list[str]]) -> None:
        # No automatic POST retry: a timeout can occur after the server committed.
        self._request("POST", self._range_url("A:L") + ":append",
                      params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                      json={"majorDimension": "ROWS", "values": rows})


def existing_index(rows: list[list[str]]) -> dict:
    if not rows:
        return {}
    if rows[0] != list(HEADERS):
        raise ValueError("Unexpected header; no changes made to existing sheet")
    index = {}
    for raw in rows[1:]:
        if not any(raw):
            continue
        if len(raw) > len(HEADERS):
            raise ValueError("Unexpected data outside the configured columns")
        row = [*raw, *([""] * (len(HEADERS) - len(raw)))]
        key = alert_key({"identifier": row[0], "senderName": row[7]})
        if key is None or key in index:
            raise ValueError("Invalid or duplicate existing ID; manual reconciliation needed")
        index[key] = row
    return index


def sync_pending(client: SheetsClient, pending_path: Path, now: datetime) -> dict:
    pending = merge_pending([], load_pending(pending_path))
    result = {"inserted": 0, "already_present": 0, "pending": len(pending), "warnings": 0, "status": "ok"}
    if not pending:
        return result
    rows = client.read_rows()
    index = existing_index(rows)
    if not rows:
        client.initialize_headers()
    missing = []
    for alert in pending:
        key = alert_key(alert)
        if key in index:
            result["already_present"] += 1
            if row_values(alert, now)[:-1] != index[key][:-1]:
                result["warnings"] += 1
                LOG.warning("Existing ID %s differs; no overwrite", key[1])
        else:
            missing.append(alert)
    pending = missing
    save_pending(pending_path, pending)
    valid = []
    for alert in pending:
        row = row_values(alert, now)
        if any(len(cell) > 50000 for cell in row):
            LOG.warning("Cell exceeds Sheets size limit; ID %s kept pending", alert_key(alert)[1])
            result["warnings"] += 1
        else:
            valid.append((alert, row))
    for start in range(0, len(valid), 100):
        batch = valid[start:start + 100]
        uncertain = False
        try:
            client.append_rows([row for _, row in batch])
        except Exception as error:
            LOG.warning("Sheets append uncertain (%s); reconciling before any retry", type(error).__name__)
            uncertain = True
        # Always verify keys, including an apparently successful append.
        try:
            confirmed = existing_index(client.read_rows())
        except Exception as error:
            LOG.warning("Sheets verification failed (%s); queue retained", type(error).__name__)
            result["warnings"] += 1
            break
        keys = {alert_key(a) for a, _ in batch} & confirmed.keys()
        result["inserted"] += len(keys)
        pending = [a for a in pending if alert_key(a) not in keys]
        save_pending(pending_path, pending)
        if uncertain or len(keys) != len(batch):
            result["warnings"] += 1
            break
    result["pending"] = len(pending)
    result["status"] = "pending" if pending else "ok"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--pending-path", type=Path,
                        default=Path(os.getenv("SHEETS_PENDING_PATH", ".cache/sheets_pending.json")))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.dry_run:
            pending = merge_pending([], load_pending(args.pending_path))
            now = datetime.now(timezone.utc)
            for alert in pending:
                row = row_values(alert, now)
                if len(row) != 12 or any(len(cell) > 50000 for cell in row):
                    raise ValueError("Candidate exceeds supported row schema/size")
            print(json.dumps({"mode": "dry-run", "candidates": len(pending), "columns": len(HEADERS)}))
            return 0
        require_production()
        if not args.pending_path.is_file():
            raise ValueError("No captured queue to synchronize")
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=SCOPES)
        with AuthorizedSession(credentials) as session:
            client = SheetsClient(session, os.environ["SHEETS_SPREADSHEET_ID"],
                                  int(os.getenv("SHEETS_SHEET_ID", "0")))
            result = sync_pending(client, args.pending_path, datetime.now(timezone.utc))
        print(json.dumps(result))
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as output:
                output.write("\n### Sheets sync\n" + "\n".join(f"- {k}: {v}" for k, v in result.items()) + "\n")
        return 1 if result["pending"] else 0
    except Exception as error:
        # HTTP bodies and credential details must not leak into public workflow logs.
        LOG.error("Sheets synchronization failed (%s); pending queue preserved", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

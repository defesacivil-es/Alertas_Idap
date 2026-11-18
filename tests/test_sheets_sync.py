import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.sheets_registry import HEADERS, TARGET_SENDER, save_pending, load_pending, row_values
from scripts.sync_alerts_sheets import SheetsClient, sync_pending, require_production

NOW = datetime(2026, 11, 17, 15, tzinfo=timezone.utc)


def alert(identifier="1", **fields):
    return dict(identifier=identifier, senderName=TARGET_SENDER, **fields)


class MemoryClient:
    def __init__(self, rows=None, fail=None):
        self.rows = [] if rows is None else rows
        self.fail = fail
        self.calls = 0

    def read_rows(self):
        return self.rows

    def initialize_headers(self):
        self.rows = [list(HEADERS)]

    def append_rows(self, rows):
        self.calls += 1
        if self.fail != "before":
            self.rows.extend(rows)
        if self.fail:
            raise TimeoutError("response lost")


class SyncTests(unittest.TestCase):
    def run_sync(self, client, records):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "queue.json"
            save_pending(path, records)
            result = sync_pending(client, path, NOW)
            return result, load_pending(path)

    def test_append_and_repeat_with_raw_formula_content(self):
        client = MemoryClient()
        records = [alert(description="=1+1"), alert()]
        result, remaining = self.run_sync(client, records)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(remaining, [])
        self.assertEqual(client.rows[1][9], "=1+1")
        result, _ = self.run_sync(client, records)
        self.assertEqual(client.calls, 1)
        self.assertEqual(result["already_present"], 1)

    def test_timeout_after_write_is_reconciled_without_second_append(self):
        client = MemoryClient(fail="after")
        result, remaining = self.run_sync(client, [alert()])
        self.assertEqual(remaining, [])
        self.assertEqual(client.calls, 1)
        self.assertEqual(result["inserted"], 1)

    def test_timeout_before_write_retains_queue(self):
        result, remaining = self.run_sync(MemoryClient(fail="before"), [alert()])
        self.assertEqual(len(remaining), 1)
        self.assertEqual(result["status"], "pending")

    def test_schema_and_duplicate_keys_fail_closed(self):
        row = row_values(alert(), NOW)
        for rows in [[[], row], [["wrong"]], [list(HEADERS), row, row]]:
            with self.subTest(rows=rows):
                client = MemoryClient(rows)
                with self.assertRaises(ValueError):
                    self.run_sync(client, [alert("2")])
                self.assertEqual(client.calls, 0)

    def test_oversized_message_does_not_block_other_records(self):
        result, remaining = self.run_sync(MemoryClient(), [alert("big", description="a" * 50001), alert("small")])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(remaining[0]["identifier"], "big")
        self.assertEqual(result["status"], "pending")

    def test_no_credentials_on_nonproduction(self):
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/development", "GITHUB_REPOSITORY": "defesacivil-es/Alertas_Idap"}):
            with self.assertRaises(ValueError):
                require_production()

    def test_client_resolves_renamed_sheet_and_sends_raw(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        class Session:
            def __init__(self): self.calls = []
            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                if url.endswith("/book"):
                    return Response({"sheets": [{"properties": {"sheetId": 0, "title": "Nova aba",
                        "gridProperties": {"rowCount": 1001, "columnCount": 26}}}]})
                return Response({"values": []})
        session = Session()
        client = SheetsClient(session, "book", 0)
        self.assertEqual(client.read_rows(), [])
        self.assertEqual(len(session.calls), 3)
        client.append_rows([row_values(alert(), NOW)])
        params = session.calls[-1][2]["params"]
        self.assertEqual(params["valueInputOption"], "RAW")
        self.assertEqual(params["insertDataOption"], "INSERT_ROWS")
        self.assertIn("Nova%20aba", session.calls[-1][1])

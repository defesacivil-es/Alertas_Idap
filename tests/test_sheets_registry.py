import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.sheets_registry import (
    TARGET_SENDER, HEADERS, alert_key, row_values, load_pending, merge_pending, save_pending,
)


def alert(**changes):
    return dict(identifier="123/2026", senderName=TARGET_SENDER, **changes)


class RegistryTests(unittest.TestCase):
    def test_key_fallback_and_filter(self):
        self.assertEqual(alert_key(alert()), (TARGET_SENDER.casefold().replace("í", "i"), "123/2026"))
        self.assertEqual(alert_key({"identifier": "UNKNOWN", "entry_id": "valid", "senderName": TARGET_SENDER})[1], "valid")
        self.assertIsNone(alert_key({"identifier": "UNKNOWN", "senderName": TARGET_SENDER}))
        self.assertIsNone(alert_key({"identifier": "1", "senderName": "Outro emissor"}))

    def test_twelve_columns_dates_municipalities_and_formula_text(self):
        a = alert(sent="2026-11-17T15:00:00Z", description="=1+1",
                  affected_municipios=[{"municipio_nome": "Serra"}, {"municipio_nome": "Vitória"},
                                       {"municipio_nome": "Serra"}])
        row = row_values(a, datetime(2026, 11, 17, 16, tzinfo=timezone.utc))
        self.assertEqual(len(row), len(HEADERS))
        self.assertEqual(row[0:5], ["123/2026", "17/11/2026 12:00:00", "", "", "Serra; Vitória"])
        self.assertEqual(row[9], "=1+1")
        self.assertEqual(row[11], "17/11/2026 13:00:00")

    def test_queue_preserves_first_content_and_completes_municipalities(self):
        old = alert(description="first", expires="2001-01-01T00:00:00Z")
        new = alert(description="second", affected_municipios=[{"municipio_nome": "Serra"}])
        merged = merge_pending([old], [new, new])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["description"], "first")
        self.assertEqual(merged[0]["affected_municipios"], new["affected_municipios"])

    def test_corrupt_queue_and_atomic_write_failure(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pending.json"
            self.assertEqual(load_pending(path), [])
            save_pending(path, [alert()])
            before = path.read_bytes()
            with patch("scripts.sheets_registry.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    save_pending(path, [])
            self.assertEqual(path.read_bytes(), before)
            path.write_text('{"version": 1, "alerts": "bad"}')
            with self.assertRaises(ValueError):
                load_pending(path)
            path.write_text("broken")
            with self.assertRaises(ValueError):
                load_pending(path)

    def test_explicit_area_names_and_invalid_dates(self):
        a = alert(areaDesc="Guarapari/ES, Serra/ES", sent="bad")
        self.assertEqual(row_values(a, datetime.now(timezone.utc))[4], "Guarapari; Serra")
        self.assertEqual(row_values(a, datetime.now(timezone.utc))[1], "")
        self.assertEqual(row_values(alert(areaDesc="regiao de risco"), datetime.now(timezone.utc))[4], "")

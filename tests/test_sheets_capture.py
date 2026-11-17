import os
import io
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

from scripts import idap_daily_maps as collector
from scripts.sheets_registry import TARGET_SENDER, load_pending


def record(identifier):
    values = {f.name: None for f in fields(collector.AlertRecord)}
    values.update(identifier=identifier, entry_id=identifier, senderName=TARGET_SENDER,
                  sent="2001-01-01T00:00:00Z", onset="2001-01-01T00:00:00Z",
                  expires="2001-01-02T00:00:00Z", nivel="Baixo", polygon_points=0,
                  has_geocode=False, areaDesc="Serra/ES")
    return collector.AlertRecord(**values)


class CaptureTests(unittest.TestCase):
    def test_invalid_polygon_does_not_drop_cap_fields_before_capture(self):
        xml = f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>bad-geometry</id>
        <content><alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
        <identifier>bad-geometry</identifier><sent>2001-01-01T00:00:00Z</sent>
        <info><senderName>{TARGET_SENDER}</senderName>
        <onset>2001-01-01T00:00:00Z</onset><expires>2001-01-02T00:00:00Z</expires>
        <description>Preserve this alert</description><area><areaDesc>Serra/ES</areaDesc>
        <polygon>nan,nan nan,nan nan,nan</polygon></area></info>
        </alert></content></entry></feed>'''.encode()
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            path = Path(d)
            with patch.dict(os.environ, {
                "SHEETS_CAPTURE_ENABLED": "true", "SHEETS_PENDING_PATH": str(path / "pending.json"),
                "OUT_DIR": str(path / "out"), "STATE_PATH": str(path / "state.json"),
                "HISTORY_PATH": str(path / "history.json"), "ALERTS_GEOJSON_PATH": str(path / "alerts.geojson"),
            }), patch.object(collector, "_read_url", return_value=xml):
                self.assertEqual(collector.main(), 0)
            pending = load_pending(path / "pending.json")
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["description"], "Preserve this alert")

    def run_collector(self, d, enabled, fail_mesh=False):
        path = Path(d)
        feed = record("new")
        if fail_mesh:
            feed.onset = "2099-01-01T00:00:00Z"
            feed.expires = "2099-01-02T00:00:00Z"
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.dict(os.environ, {
                "SHEETS_CAPTURE_ENABLED": str(enabled).lower(),
                "SHEETS_PENDING_PATH": str(path / "pending.json"),
                "OUT_DIR": str(path / "out"), "STATE_PATH": str(path / "state.json"),
                "HISTORY_PATH": str(path / "history.json"),
                "ALERTS_GEOJSON_PATH": str(path / "alerts.geojson"),
            }))
            stack.enter_context(patch.object(collector, "_read_url", return_value=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry/></feed>'))
            stack.enter_context(patch.object(collector, "_parse_cap_from_entry", return_value=(feed, None)))
            stack.enter_context(patch.object(collector, "_load_history", return_value=[record("old")]))
            stack.enter_context(patch.object(collector, "_load_municipios_gdf", side_effect=ValueError("mesh failure")))
            return collector.main()

    def test_old_expired_geometryless_records_survive_and_repeat_once(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_collector(d, True), 0)
            self.assertEqual(self.run_collector(d, True), 0)
            rows = load_pending(Path(d) / "pending.json")
            self.assertEqual({r["identifier"] for r in rows}, {"new", "old"})
            self.assertEqual(len(rows), 2)
            self.assertNotIn("geometry_wkt", rows[0])

    def test_mesh_failure_does_not_lose_captured_records(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_collector(d, True, fail_mesh=True), 4)
            self.assertEqual(len(load_pending(Path(d) / "pending.json")), 2)

    def test_disabled_capture_leaves_no_queue(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_collector(d, False), 0)
            self.assertFalse((Path(d) / "pending.json").exists())

"""Pure alert serialization and durable pending queue; no Google access."""

import json
import logging
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)
TARGET_SENDER = "Defesa Civil Estadual do Esp\u00edrito Santo"
HEADERS = (
    "ID do alerta", "Emiss\u00e3o", "In\u00edcio da vig\u00eancia",
    "Fim da vig\u00eancia", "Munic\u00edpios atingidos", "Evento", "N\u00edvel",
    "Emissor", "T\u00edtulo", "Mensagem", "Orienta\u00e7\u00f5es", "Registrado em",
)


def normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


def alert_key(alert: dict) -> tuple[str, str] | None:
    sender = normalized(alert.get("senderName"))
    if sender != normalized(TARGET_SENDER):
        return None
    for field in ("identifier", "entry_id"):
        identifier = str(alert.get(field) or "").strip()
        if identifier and identifier.casefold() not in {"unknown", "null", "none"}:
            return sender, identifier
    return None


def municipality_names(alert: dict) -> list[str]:
    names = [item.get("municipio_nome", "").strip()
             for item in (alert.get("affected_municipios") or []) if isinstance(item, dict)]
    names.extend(re.findall(r"([^,;\n]+?)/ES\b", str(alert.get("areaDesc") or ""), re.I))
    if alert.get("municipio_nome"):
        names.append(str(alert["municipio_nome"]).strip())
    unique = {}
    for name in names:
        name = name.strip()
        if name:
            unique.setdefault(normalized(name), name)
    return sorted(unique.values(), key=normalized)


def _date_text(value) -> str:
    if not value:
        return ""
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("timezone missing")
        return date.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError):
        LOG.warning("Invalid or timezone-free timestamp omitted from Sheets row")
        return ""


def row_values(alert: dict, registered_at: datetime) -> list[str]:
    key = alert_key(alert)
    if key is None:
        raise ValueError("Alert has no eligible sender/identifier")
    names = municipality_names(alert)
    if not names:
        LOG.warning("Municipalities unavailable for ID %s", key[1])
    return [
        key[1], _date_text(alert.get("sent")), _date_text(alert.get("onset")),
        _date_text(alert.get("expires")), "; ".join(names),
        str(alert.get("event") or ""), str(alert.get("nivel") or ""),
        str(alert.get("senderName") or ""), str(alert.get("headline") or ""),
        str(alert.get("description") or ""), str(alert.get("instruction") or ""),
        _date_text(registered_at),
    ]


def load_pending(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("alerts"), list)
            or any(not isinstance(a, dict) or not alert_key(a) for a in data["alerts"])):
        raise ValueError("Invalid Sheets queue; preserve file and recover manually")
    return data["alerts"]


def merge_pending(pending: list[dict], candidates: list[dict]) -> list[dict]:
    result = {}
    for alert in [*pending, *candidates]:
        key = alert_key(alert)
        if key is None:
            LOG.warning("Sheets candidate rejected: invalid ID or ineligible sender")
            continue
        if key not in result:
            result[key] = deepcopy(alert)
            continue
        previous = result[key]
        if any(previous.get(k) != alert.get(k) for k in ("description", "headline", "expires")):
            LOG.warning("Different contents for existing ID %s; first version preserved", key[1])
        if alert.get("affected_municipios"):
            previous["affected_municipios"] = list({
                normalized(item.get("municipio_nome", "")): item
                for item in [*(previous.get("affected_municipios") or []), *alert["affected_municipios"]]
                if isinstance(item, dict) and item.get("municipio_nome")
            }.values())
    return list(result.values())


def save_pending(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "alerts": records}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

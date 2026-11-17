"""Read `.env` and point the Elastic variables at the Serverless project.

The simplified demo runs on an Elastic Cloud Serverless project. Its connection values are kept in `.env` as
ELASTIC_CLOUD_SERVERLESS_ELASTICSEARCH, ELASTIC_CLOUD_SERVERLESS_KIBANA and ELASTIC_CLOUD_SERVERLESS_API_KEY. This module copies
them over ELASTICSEARCH_URL, KIBANA_URL and ELASTIC_API_KEY, the names the rest of the code reads, even when `make` has already
exported the old (Hosted) values from the same file. Set COLDCHAIN_TARGET=hosted to keep the old values.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = {"ELASTICSEARCH_URL": "ELASTIC_CLOUD_SERVERLESS_ELASTICSEARCH", "KIBANA_URL": "ELASTIC_CLOUD_SERVERLESS_KIBANA",
       "ELASTIC_API_KEY": "ELASTIC_CLOUD_SERVERLESS_API_KEY"}


def load_env() -> dict[str, str]:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    if os.environ.get("COLDCHAIN_TARGET", "serverless") == "serverless" and all(os.environ.get(v) for v in MAP.values()):
        for target, source in MAP.items():
            os.environ[target] = os.environ[source]
    return os.environ  # type: ignore[return-value]

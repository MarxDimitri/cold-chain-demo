from datetime import datetime, timezone

from coldchain.infra import pick_since


def _v(key, hour):
    return {"Key": key, "LastModified": datetime(2026, 11, 16, hour, 0, tzinfo=timezone.utc)}


def test_pick_since_keeps_only_versions_at_or_after_the_time():
    versions = [_v("raw/dataset=coldchain.audit/old", 7), _v("raw/dataset=coldchain.audit/edge", 9), _v("raw/dataset=netflow.log/new", 11)]
    got = pick_since(versions, datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc))
    assert [v["Key"].split("/")[-1] for v in got] == ["edge", "new"]

"""Make room for a live replay on the real clock (`make demo`).

    python -m coldchain.prep [MINUTES] [--preroll-hours H]
    python -m coldchain.prep clean SINCE      # after the run: delete the indexed replay documents ingested since SINCE

The replay writes its own normal telemetry for every store, so any baseline documents in the indexed detect streams from
5 minutes ago to MINUTES ahead (default 60) would double every cabinet minute: they are deleted before the replay starts.
Then the pre-roll (default 6 hours, 0 = off) fills the gap between the end of the indexed baseline and now with normal data
written to S3 and read by the collector, so the dashboards and rule 2 start with a day of context.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

from .elastic import client

STREAMS = ["logs-coldchain.audit-default", "metrics-coldchain.case-default", "logs-netflow.summary-default",
           "logs-coldchain.probe-default"]
ROTATION = 10  # minutes per pre-roll file


def clean(since: str) -> None:
    """After a live run: delete the indexed documents ingested since SINCE (ISO time) from the four detect streams."""
    es = client()
    for ix in STREAMS:
        r = es.delete_by_query(index=ix, query={"range": {"event.ingested": {"gte": since}}}, conflicts="proceed",
                               refresh=True, wait_for_completion=True)
        print(f"clean: {ix}: removed {r['deleted']} documents ingested since {since}")
    r = es.delete_by_query(index=".alerts-security.alerts-default", conflicts="proceed", refresh=True, wait_for_completion=True,
                           query={"bool": {"filter": [{"range": {"@timestamp": {"gte": since}}},
                                                      {"prefix": {"kibana.alert.rule.name": "Cold chain:"}}]}})
    print(f"clean: alerts of the cold-chain rules since {since}: removed {r['deleted']}")


def plan_window(end: int, last: int | None, hours: float) -> tuple[int, int] | None:
    """The pre-roll window (begin, end) in epoch seconds, or None when the index already reaches END.

    It starts HOURS before END, or one minute after the newest indexed telemetry LAST, whichever is later. Pre-roll files
    rotate every 10 minutes, the backfilled baseline hourly: if the window began in the first 10 minutes of the baseline's
    last hour, its first file would get the same key as that baseline file, so it begins at minute 10 instead.
    """
    begin = end - int(hours * 3600)
    if last is not None:
        begin = max(begin, last // 60 * 60 + 60)
        if begin // 3600 == last // 3600 and begin % 3600 < ROTATION * 60:
            begin = begin // 3600 * 3600 + ROTATION * 60
    return (begin, end) if end - begin >= 120 else None


def _newest(es) -> int | None:
    r = es.search(index=STREAMS[1], size=0, aggs={"mx": {"max": {"field": "@timestamp"}}})
    v = r["aggregations"]["mx"]["value"]
    return int(v // 1000) if v else None


def preroll(hours: float, seed: int = 42, timeout: int = 900) -> None:
    """Write normal telemetry, probes, flow summaries and audit for the gap before the replay, through S3 and the collector.

    Without it a demo on a later day starts on an empty index: the Act 1 chart is blank before T0 and rule 2 mistakes the
    tail of a defrost for a warm cabinet, because the relay-on readings that explain it are missing. Waits until the
    collector has indexed it, and records where it ended so the replay fills the minutes in between.
    """
    from .audit import audit_history
    from .chain import ROOT, load_attack, load_chain, parse_ts
    from .network import flows
    from .sink import make_sink, write_records
    from .telemetry import write_probe, write_telemetry

    es = client()
    end = int(time.time()) // 60 * 60
    es.indices.refresh(index=STREAMS[1])
    last = _newest(es)
    win = plan_window(end, last, hours)
    if win is None:
        print("preroll: the index already reaches now, nothing to write")
        return
    begin, end = win
    print(f"preroll: {datetime.fromtimestamp(begin, timezone.utc):%Y-%m-%d %H:%M}Z to {datetime.fromtimestamp(end, timezone.utc):%H:%M}Z "
          f"({(end - begin) // 60} min, 20 stores)", flush=True)
    chain, attack = load_chain(), load_attack()
    t0 = parse_ts(attack["t0"])
    probes = [{**p, "attacker_ip": attack["attacker_ip"]} for p in attack["probes"]]
    sink = make_sink("s3")
    minutes = (end - begin) // 60
    f_epoch = -(-begin // 300) * 300
    started = time.time()
    for store in chain.stores:
        write_telemetry(sink, chain, store, "detect", begin, minutes, 1, ROTATION, seed)
        write_probe(sink, chain, store, "detect", begin, minutes, ROTATION, seed)
        audit = audit_history(chain, store, datetime.fromtimestamp(begin, timezone.utc),
                              datetime.fromtimestamp(end, timezone.utc), seed, probes, t0)
        write_records(sink, "detect", "coldchain.audit", store.id, audit, ROTATION)
        # whole 5-minute windows up to the next boundary: the replay's own flows start at the first boundary at or after END
        _, summary = flows(chain, store, f_epoch, (-(-end // 300) * 300 - f_epoch) / 86400, seed)
        write_records(sink, "detect", "netflow.summary", store.id, summary, ROTATION)
    print(f"preroll: {sink.files} files, {sink.bytes / 1e6:.1f} MB written in {time.time() - started:.0f} s; waiting for the collector",
          flush=True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(10)
        es.indices.refresh(index=STREAMS[1])
        newest = _newest(es)
        if newest is not None and newest >= end - 60:
            break
        print(f"  indexed up to {datetime.fromtimestamp(newest, timezone.utc):%H:%M}Z" if newest else "  nothing indexed yet", flush=True)
    else:
        print("preroll: the collector did not catch up in time; the replay starts anyway", file=sys.stderr)
    STATE = ROOT / ".replay"
    STATE.mkdir(exist_ok=True)
    (STATE / "preroll.json").write_text(json.dumps({"end": end}))
    print(f"preroll: indexed, the replay fills from {datetime.fromtimestamp(end, timezone.utc):%H:%M}Z", flush=True)


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if args[:1] == ["clean"]:
        return clean(args[1])
    hours = 6.0
    if "--preroll-hours" in args:
        i = args.index("--preroll-hours")
        hours = float(args[i + 1])
        del args[i:i + 2]
    ahead = int(args[0]) if args else 60
    now = datetime.now(timezone.utc)
    q = {"range": {"@timestamp": {"gte": (now - timedelta(minutes=5)).isoformat(), "lt": (now + timedelta(minutes=ahead)).isoformat()}}}
    es = client()
    for ix in STREAMS:
        r = es.delete_by_query(index=ix, query=q, conflicts="proceed", refresh=True, wait_for_completion=True)
        print(f"prep: {ix}: removed {r['deleted']} baseline documents")
    if hours > 0:
        preroll(hours)


if __name__ == "__main__":
    main()

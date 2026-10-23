"""Offline match-evaluation harness.

Pipeline (source-agnostic): tick ``records`` -> ``metrics`` -> ``report``.

A *tick record* is a plain dict with the keys ``team``, ``position``,
``commandType``, ``latency_ms`` and ``success`` (see ``metrics`` for the schema).
Any producer that emits that shape can feed the pipeline unchanged:

* ``run_eval.simulate_match`` is the offline, seeded, deterministic producer used
  today (no AWS, no live model).
* A FUTURE ``cloudwatch_source.records_from_cloudwatch(...)`` adapter would pull
  the identical record shape from CloudWatch logs/traces and feed the SAME
  ``metrics.command_breakdown`` / ``metrics.agent_performance`` / ``report``
  pipeline. Because ``metrics`` is pure and source-agnostic, that adapter lands
  with zero changes to the metrics or report code. It is intentionally NOT
  implemented here (YAGNI) — only the record contract is fixed.
"""

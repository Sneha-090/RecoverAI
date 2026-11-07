# Repeatable demo guide

Use the existing D drive environment. No new package or provider credential is
needed for the offline walkthrough or synthetic benchmark.

```bat
cd /d D:\RecoverAI
.venv\Scripts\python.exe -m scripts.offline_demo
.venv\Scripts\python.exe -m ML.benchmark_policies
```

Open `reports/offline_demo.html`. It is self-contained and can be opened as a
local file without a server. **Replay all** advances the recorded steps roughly
six seconds apart; Previous/Next and the six scenario buttons allow manual
navigation. These controls replay a saved trace; they do not send payments.
Regenerate the artifacts with the commands above to run the services again.

If a local browser does not open local HTML directly, serve only the generated
reports directory:

```bat
.venv\Scripts\python.exe -m http.server 8766 --bind 127.0.0.1 --directory reports
```

Then open [the offline replay](http://127.0.0.1:8766/offline_demo.html).
Do not serve the project root, which contains local configuration.

## Approximately three-minute walkthrough

| Time | Recorded scenario | Evidence to point at |
| --- | --- | --- |
| 0:00–0:15 | State the demo scope | Fake provider, real services, isolated DB, not merchant revenue |
| 0:15–0:45 | Normal failure and duplicate | One resource, rejected bad signature, pending until capture, one result |
| 0:45–1:05 | Human approval | Zero provider resources before approval; one afterward |
| 1:05–1:35 | Lost response | Existing intent/resource verified; creation count stays one |
| 1:35–2:00 | Late old capture | Correct older execution settles; newer result is untouched |
| 2:00–2:20 | Review expiry | Failed case closes with zero provider creations |
| 2:20–2:45 | Early-event replay | Capture waits, execution persists, replay processes once |
| 2:45–3:00 | Benchmark evidence | ML-versus-rules interval crosses zero; no invented uplift claim |

The timer is a presentation suggestion, not a recorded video or a latency
benchmark. The HTML and Markdown show the actual fixture results. All six
scenarios validate their expected state transitions during generation.

## Evidence files

- [Offline scenario results](reports/OFFLINE_DEMO.md)
- [Machine-readable trace](reports/offline_demo.json)
- [Recorded interactive replay](reports/offline_demo.html)
- [Matched benchmark](reports/POLICY_BENCHMARK.md)
- [Policy decisions](reports/policy_decisions.csv)
- [Architecture and limits](ARCHITECTURE.md)
- [Actual Razorpay Test Mode record](TEST_MODE_VERIFICATION.md)

For the authenticated dashboard, use the local operator configuration and open
**Policy Benchmark** for the matched results or **Recovery Review** for stuck
cases. The offline runner does not seed demonstration cases into that database.
The real database can therefore show no stuck cases; that is an expected state.

## Reproduction and data safety

Every run creates a uniquely named SQLite file under `.venv/demo_runs`. It does
not reuse/delete merchant data, modify `.env`, or make provider requests. The
old `python -m scripts.live_demo` command now invokes the same safe offline run.
Generated JSON includes model/source fingerprints. Text fingerprints normalize
newlines so Windows and Linux checkouts can verify the same evidence.

CI regenerates both reports and uploads artifacts. A green local run is not a
remote-CI result; inspect the linked GitHub Actions run. Recorded test-mode and
synthetic results must remain clearly separated when sharing the project.

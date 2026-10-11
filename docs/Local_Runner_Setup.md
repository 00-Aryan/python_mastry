# Local WSL2 execution worker

Use Linux x86_64, Python 3.12 through uv and a non-root account. On WSL2 enable
systemd in `/etc/wsl.conf` (`[boot] systemd=true`) and restart WSL from Windows.
This requires operator changes outside the repository. Install distribution packages
`bubblewrap`, `libseccomp2` and systemd; the inspected host already has Bubblewrap
0.11.1. A running `systemctl --user` manager and writable delegated cgroup v2
cpu/memory/pids controllers are mandatory. Check `systemctl --user status` and
`cat /sys/fs/cgroup/cgroup.controllers`. Availability is established by the CLI probe,
not merely by the presence of binaries. No Docker/Podman fallback exists.

From a fresh clone:

```bash
uv sync --locked
cp .env.example .env
# Configure DATABASE_URL and seed the local database identity per README.
uv run alembic upgrade head
uv run mastery-worker build-runtime --runtime .local-runner/runtime
uv run mastery-worker probe --runtime .local-runner/runtime
uv run mastery-worker provision --runtime .local-runner/runtime --credential .local-runner/worker.json
uv run mastery-worker serve --runtime .local-runner/runtime --credential .local-runner/worker.json
```

In a separate terminal run the API normally. Set `LOCAL_RUNNER_ENABLED=true` in its
local configuration; the worker's fresh readiness is still required. Do not place
credentials in the runtime image. Runtime/key files are ignored, keys are created
exclusively with mode 0600, only their SHA-256 hash is stored in PostgreSQL. Treat
the worker account/database/operator as trusted. Revoke workers using trusted database
administration (`execution_worker_identities.revoked=true`); no learner/admin HTTP
shortcut exists. Stop with SIGTERM/Ctrl-C. `once` provides one bounded dispatch;
readiness is withdrawn on orderly exit. Rebuild into a new directory and provision a
new worker after changing runtime/control code: image/profile hashes are immutable
policy pins, and existing jobs keep their old worker/policy identity.

`runtime_image.py` copies a curated standard library/interpreter and its installed ELF
libraries, seals files and writes an exact hash inventory. `sandbox_launcher.py` opens
the seccomp descriptor in the trusted service and execs Bubblewrap. `local_sandbox.py`
checks live service/cgroup limits, exchanges bounded JSON and kills/cleans the complete
unit. `sandbox_bootstrap.py` runs only in isolation, with no oracle or credentials.
`local_runner.py` grades outside isolation without any database transaction.
The application `local_evaluation_runner.py` authenticates and owns short provenance transactions.
`worker_authority.py` owns operator provisioning/authentication/readiness;
`worker_cli.py` runs separately from the API and reuses B6a orchestration.

Limits: 128 MiB memory, zero swap, 16 tasks, 100% CPU quota, two CPU seconds per process,
three seconds per test service, ten-second job admission-to-test loop budget, 1 MiB
writable tmpfs, 64 KiB combined output, 128 KiB input envelope, depth 20 returned JSON,
and at most 64 tests. A final case can consume its three-second limit after the job
loop's ten-second budget check; total execution remains below the 30-second lease.
Published bundles exceeding the protocol bounds are unsupported infrastructure, not
learner errors. No raw diagnostics are published.

This local shared-kernel sandbox is not a production security certification or a VM.
The host kernel, trusted runtime, operator files and systemd manager remain trusted.
It does not protect against kernel vulnerabilities or a compromised worker account.
No live host directories, sockets, site-packages, secrets or expected answers are
mounted. Writable storage/namespaces are new for every case. The Python runtime and
bootstrap are readable; neither contains private grading data. Non-root, dropped
capabilities, no_new_privs and seccomp deny process creation/network/privilege changes.
A real SIGKILL can orphan a systemd service until its independent runtime limit; this
bounded interval is explicitly tested and is not described as instant cleanup.

Run real checks only where all controls are available:

```bash
RUN_ISOLATION_TESTS=1 TEST_DATABASE_URL=postgresql://…/mastery_test uv run pytest -q -W error
uv run ruff check .
uv run ruff format --check .
uv run mypy src migrations
uv build
```

Without `RUN_ISOLATION_TESTS=1` real execution cases skip explicitly. No fake adapter
is enabled in development; existing fakes remain defined only in test modules.
Publication verification, recommendations, mastery and deployment remain future work.

# B6b local isolated execution

Decision recorded before implementation, 10 October 2026. Inspected WSL2 Linux
6.18.33.2, non-root UID 1000, Bubblewrap 0.11.1, libseccomp, a running systemd user
manager and cgroup v2 CPU/memory/pids controls. Docker/Podman are absent. A trusted
true executable successfully used mandatory namespaces and systemd resource limits.

## Selected backend and trust boundary

Use Bubblewrap plus systemd user services and an explicit libseccomp allowlist.
Official sources: [Bubblewrap security/limitations](https://github.com/containers/bubblewrap/blob/main/README.md),
[systemd execution](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html),
[systemd service lifetime](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml),
[cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html), and
[libseccomp API](https://github.com/seccomp/libseccomp/blob/main/include/seccomp.h.in).
Bubblewrap is a mechanism, not a turnkey security policy. This is a local shared-kernel
boundary, not a VM, protection from kernel vulnerabilities, or production deployment.
The operator, worker, runtime builder, Python runtime, kernel, systemd and libseccomp
are trusted. Learner code, stdout/stderr and returned values are untrusted.

Build a curated read-only Python 3.12 runtime image from the installed trusted runtime,
with an exact file/hash manifest, no site-packages, home/project directories, secrets,
container sockets or private question assets. Startup verifies its manifest, ownership,
permissions, native architecture and runtime version. The only filesystem bind is this
sealed image; no live /usr, /home, project or credentials directories are exposed.
Source and one test input travel as bounded JSON on stdin. The sandbox receives no
job IDs, lease tokens, worker keys, expected values, other tests or reference solution.
Comparison against expected values occurs in the trusted adapter, outside the sandbox.
Each test case uses fresh namespaces and storage, providing stronger separation than
one sandbox per job. Bootstrap code is readable but contains no grading oracle.

## Mandatory controls and unavailable behavior

Require non-root worker and sandbox, user/mount/PID/network/IPC/UTS/cgroup namespaces,
all capabilities dropped, no_new_privs, new session, no inherited credentials/environment,
seccomp default-deny allowlist (no socket/connect, fork/clone, ptrace, mount, namespace or
privilege-changing syscalls). Namespace/privilege/resource probes run before registration.
Every invocation verifies live systemd properties and actual cgroup files before source
is sent. Missing controls, binaries, user bus, runtime integrity or worker authentication
keep evaluation unavailable; there is no ordinary subprocess fallback.

Pilot limits: 128 MiB memory, zero swap, 16 cgroup tasks (including trusted launcher/
namespace init), one CPU maximum, two CPU seconds per process, three seconds per case,
ten-second budget checked before each case (at most thirteen seconds total), 1 MiB writable tmpfs, 64 KiB combined output, 64 tests and bounded
JSON input/return depth. Process creation/network are additionally denied by seccomp.
Systemd kills the entire control group on runtime expiry; explicit cancellation/output
limit stops that unit, with SIGKILL and bounded stop time. Fresh tmpfs disappears when
the PID namespace terminates. SIGTERM cancels active work; SIGKILL of the trusted worker
can leave the service alive only until its independent runtime limit (at most three
seconds), after which systemd kills/collects it. Real crash verification must report
this bounded orphan interval, not claim instantaneous parent-death cleanup.

## Worker identity, admission and provenance

Run a dedicated trusted worker CLI separately from the API. Provision a random worker
credential into an owner-only file; store only its hash and opaque worker identity in
PostgreSQL. Learner authentication/roles cannot register workers or supply results;
there is no result callback. The worker reauthenticates before claim/result/recovery.
A short-lived authenticated readiness heartbeat exposes only identity/policy pins to
local development admission; dead/unhealthy/revoked workers cause safe 503. The API
holds no execution adapter and never executes source. Production remains disabled.

Protocol/evaluator policy v2 adds runtime_error and pins runtime-image/isolation-profile
hashes without editing v1 policies or old jobs. Claims/results still use B6a tokens,
generations, leases, lock ordering and immutable terminal transitions. Each real run
records append-only provenance signed with the worker key, including exact source,
bundle, policy, runtime/profile hashes, generation, worker ID and sanitized outcome.
Worker keys and signature generation stay outside the sandbox. Identity strings and
learner output are not authentication. This local direct worker boundary does not add
remote TLS/signature callbacks; remote transport/deployment remain future work.

Incorrect comparisons, syntax/runtime faults and learner resource violations are
failed outcomes; backend/control failures are infrastructure_error with bounded B6a
retry. No raw output, returned value, hidden-test counts/inputs, traceback or exception
message enters public status/diagnostics. Results never award independent eligibility,
finish attempts, calculate mastery or implement publication verification.

## Verification required

First rerun the B6a PostgreSQL baseline. Verify startup denial/missing controls and
image integrity; then real correct/incorrect/syntax/runtime sources, loops, output,
fork attempts, memory, tmpfs exhaustion, filesystem/network/credential/private-asset
isolation, fresh state, full-workload cleanup/cancellation and an actual killed worker
process. Test authenticated readiness/revocation, immutable provenance, duplicates,
stale generations, actual abandoned lease recovery and unavailable API behavior.
Run all regressions, PostgreSQL migrations, Ruff, strict mypy and package checks. Record
real vs simulated crash cases explicitly, and report any unavailable controls/checks.

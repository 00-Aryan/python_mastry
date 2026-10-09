# B0 implementation decisions

Date: 9 October 2026

- Implement the app foundation only. Readiness explicitly reports absent database and evaluation integration rather than returning a misleading full-platform health result.
- DATABASE_URL is required and redacted even though connection setup belongs to B1. No database credential is printed, committed or validated by making a network connection in B0.
- Production and session-authentication startup are rejected while those capabilities are unimplemented. Local identity is a future B1 seed, not an authentication mechanism for hosted use.
- Each app owns its settings. Logging uses one idempotently configured namespaced handler and request-local context; factories do not duplicate handlers.
- Middleware order from outside to inside: request context, host guard, CORS, body guard, FastAPI routes. Thus preflight cannot skip host checks and body-guard errors retain ordinary CORS handling.
- Request bodies are bounded before FastAPI parsing, including requests without Content-Length. Error details omit rejected input.
- The generated public schema contains only released routes. No fake question, timer or evaluation endpoints are provided.
- Installed Starlette's TestClient prefers httpx2; this was verified against its installed source. Use httpx2 in the development group rather than its deprecated httpx fallback. This updates the earlier dependency plan without changing application API behavior.
- Learning bounds and Bayesian priors are not exposed as invented active policies. Public learning capabilities and attempt modes remain empty until implemented.
- Packaging uses a src/mastery_backend module and the mastery-backend launcher. uv.lock captures resolved versions; tooling runs through uv.

Known boundary: B0 is local-only and does not implement learner authentication, DB readiness, migrations, rate limits or execution isolation. All are tracked in the existing contracts and future increments.

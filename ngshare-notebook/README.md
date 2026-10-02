# ngshare-notebook

In-house build of [ngshare](https://github.com/LibreTexts/ngshare), the
nbgrader exchange service used for course assignment sharing. Replaces the
`libretexts/ngshare` image previously pulled from Docker Hub.

## Why we build this ourselves instead of using the upstream Docker Hub image

The upstream image hadn't been rebuilt in years and was never scanned for
vulnerabilities. Building it ourselves gets us:

- **A current, scanned image.** This is built on a regularly-updated base
  and pushed through our own ECR pipeline, which scans on push. The
  upstream image had none of that - whatever it shipped with in 2022 is
  still what it shipped with.
- **Pinned, chosen dependency versions**, instead of "whatever pip resolved
  on the day the upstream image happened to be built."
- **A reproducible, auditable artifact.** Built once per commit and pushed
  under that commit's short-SHA tag - the same bytes everywhere, instead of
  a floor like `jupyterhub>=1.1.0` resolving to whatever's newest on build
  day. Currently referenced by tag (not digest) in
  `config-ngshare-keycloak.yaml` in the values repo; see that repo for
  which tag it's currently pointed at.

## Why there's a `vendor/` folder

`vendor/` is a copy of ngshare's own source code, pinned at a specific
upstream commit. We copy it into our own repo instead of doing
`git clone` at build time for one reason: ngshare is a small,
single-maintainer project with no recent releases. A build step that
depends on that repository still being reachable on GitHub is a risk we
don't need to carry - if that repository ever disappears, goes private, or
changes hands, a build that still has to reach out to it breaks
permanently. Vendoring means our build only ever depends on this
repository (`jupyter-images`) staying available.

The tradeoff: bumping to a newer upstream commit is a manual process (see
the comment block at the top of `Dockerfile` for the exact steps), not a
one-line version bump. That's intentional - a commit bump on an
unmaintained project deserves a deliberate look before it ships, not an
automatic pull.

**What's in `vendor/`:** a byte-identical copy of the pinned upstream
commit's `ngshare/` package, `setup.py`, `README.md`, `MANIFEST.in` and
`LICENSE` - nothing hand-edited, so a diff against that commit is always
meaningful. Upstream's test modules (`test_ngshare.py`, `test_dbutil.py`,
`vngshare.py`) are copied in too, since they're part of the same package
directory - the Dockerfile removes them from what actually gets
**installed** into the image (they're never imported at runtime, and
leaving them out keeps the final image smaller and reduces what a
vulnerability scanner has to look at). `database/test_database.py` is the
one exception that stays: `database/__init__.py` imports
`clear_db`/`init_db`/`dump_db` from it, so it's a runtime dependency
despite the name.

**License:** ngshare is BSD-3-Clause licensed (see `vendor/LICENSE`).
We're distributing an unmodified copy of its source inside this image;
`run.py` (below) changes runtime *behavior* without editing that source.

## Why `run.py` instead of running ngshare directly

ngshare ships as-is with a few gaps that don't meet the security
standards we hold our own services to:

- **No request logging.** ngshare's own startup code unintentionally
  disables every logger that already existed (not just its own access
  log), so there's normally no record at all of who requested what, and
  no trace of a 500 or a rejected oversized request either.
- **No CSRF protection.** ngshare doesn't turn on XSRF cookie protection
  or set `SameSite`/`HttpOnly`/`Secure` on its auth cookie.
- **No limit on request size.** A single very large request/upload isn't
  bounded, which can exhaust memory or disk.

Rather than maintaining a patched fork of ngshare's source - which would
need re-diffing by hand every time we bump the vendored commit - `run.py`
wraps ngshare at runtime and turns these things on from the outside,
without touching `vendor/`. If a future commit bump changes the internals
`run.py` depends on, it fails loudly (a clear Python error at container
startup) rather than silently shipping without these protections. See
`run.py`'s own docstring for the technical detail of what it changes and
why.

**XSRF only applies to the cookie-authenticated path.** nbgrader and the
hub always call ngshare with an `Authorization: token ...` header, never a
cookie - and a browser can't attach that header to a cross-site request,
so CSRF protection would be meaningless there anyway. `run.py` exempts
header-authenticated requests the same way JupyterHub's own `HubAuth`
does. One consequence: the web UI's own forms (`home.html`) don't embed an
XSRF token, so once this exemption is in place, the web page becomes
**read-only** - viewing still works, submitting a form from it doesn't.
Use the API (nbgrader, `ngshare-course-management`) for anything
state-changing.

**The request body-size cap and the pod's memory limit move together.**
`NGSHARE_MAX_BODY_BYTES` (default 25 MiB, set via `run.py`/the chart, not
duplicated in the Dockerfile) bounds the request body itself, but the
handler can hold several decoded copies of that payload in memory at
once - a request just under the cap can still exceed a pod memory limit
set without this in mind. If one changes, check the other.

## Files here

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image: pinned base, constrained dependencies, vendored ngshare source, `run.py` as the entrypoint |
| `requirements.txt` | The 5 direct server dependencies, pinned to exact versions |
| `constraints.txt` | Full transitive closure, exported as `PIP_CONSTRAINT` so `requirements.txt`'s install and ngshare's own setup.py-declared deps resolve against the same pins - see `Dockerfile` header for the regenerate command |
| `run.py` | Runtime hardening wrapper - see above |
| `vendor/` | Vendored ngshare source, pinned at a specific commit (see `Dockerfile` header comment for the exact commit and how to bump it) |
| `ci/smoke.sh` | Post-build smoke test: confirms a token-authenticated POST reaches ngshare's own JSON response instead of Tornado's generic XSRF 403 page |

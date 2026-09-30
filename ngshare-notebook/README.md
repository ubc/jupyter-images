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
- **A reproducible, auditable artifact.** The exact same image runs in
  every environment and is referenced by digest, not a moving tag.

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

**What's copied into `vendor/`, and what isn't:** only what's needed to
build and install the package - `ngshare/` (the source), `setup.py`,
`README.md` and `MANIFEST.in` (both required by `setup.py`'s own install
process), and `LICENSE`. Upstream's tests, docs, CI config, and its own
Dockerfile are intentionally left out - none of them are needed to install
or run the service, and leaving them out keeps the final image smaller and
reduces what a vulnerability scanner has to look at.

**License:** ngshare is BSD-3-Clause licensed (see `vendor/LICENSE`).
We're distributing an unmodified copy of its source inside this image;
`run.py` (below) changes runtime *behavior* without editing that source.

## Why `run.py` instead of running ngshare directly

ngshare ships as-is with a few gaps that don't meet the security
standards we hold our own services to:

- **No request logging.** ngshare's own startup code unintentionally
  disables the web server's access logging, so there's normally no record
  at all of who requested what.
- **No CSRF protection.** ngshare doesn't turn on XSRF cookie protection
  or set a `SameSite` cookie policy.
- **No limit on request size.** A single very large request/upload isn't
  bounded, which can exhaust memory or disk.

Rather than maintaining a patched fork of ngshare's source - which would
need re-diffing by hand every time we bump the vendored commit - `run.py`
wraps ngshare at runtime and turns these three things on from the
outside, without touching `vendor/`. If a future commit bump changes the
internals `run.py` depends on, it fails loudly (a clear Python error at
container startup) rather than silently shipping without these
protections. See `run.py`'s own docstring for the technical detail of
what it changes and why.

## Files here

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image: pinned base, pinned dependencies, vendored ngshare source, `run.py` as the entrypoint |
| `requirements.txt` | Pinned server dependencies |
| `run.py` | Runtime hardening wrapper - see above |
| `vendor/` | Vendored ngshare source, pinned at a specific commit (see `Dockerfile` header comment for the exact commit and how to bump it) |

# CW media: one-time database-authority rollout

This is an operator checklist, not a patch to LTIC's separately maintained
production manifests. The application and Newcastle operator code are built
and tested. The change removes recurring LTIC worker-registry publication;
course staff manage credentials through authenticated HTTPS after enrollment.

## 1. Admit the already-built central image

Run the existing promotion workflow from this repository's main branch:

```bash
gh workflow run promote-cw-central.yml --repo ubc/jupyter-images --ref main \
  -f digest=sha256:a21e6e403d7f6d3f3d02abd5965b165198cc65cb87ddaecb375ae4b45417a30f \
  -f receipt_ref=3f21730ba5874af7546d53a3d26af382166cb917 \
  -f publish=true -f allow_package_creation=false
```

After the workflow succeeds, pin this preserved digest for control, media and
their migration Jobs:

```text
ghcr.io/ubc/codingworkspace-central@sha256:a21e6e403d7f6d3f3d02abd5965b165198cc65cb87ddaecb375ae4b45417a30f
```

Source: `4eb49171dbdb6c4c56ce4f2040b157a1c78706d4`.
[Course image build and published-container checks](https://github.com/kevinlb1/CodingWorkspace/actions/runs/34525530347).
No image rebuild or new package is needed. Admission still uses the existing
protected environment and private destination. The supplied receipt ref holds
exactly one matching staging receipt.

## 2. Install the additive database authority

Using the migration Job's existing course-scoped migration-owner configuration:

```bash
python -m codingworkspace.media_worker_management migrate \
  --worker-issuer urn:codingworkspace:media-workers:prod
```

For staging, substitute `urn:codingworkspace:media-workers:stg`; preview uses
`:preview`. Use the matching issuer in the media settings below. The existing
collaboration course is `ai100`; do not reuse staging state or secrets in prod.

From the course checkout at receipt ref `3f21730ba5874af7546d53a3d26af382166cb917`,
apply this file with the existing approved DBA connection and actual role names:

```text
deploy/kubernetes/central-services/postgres-media-management-grants.sql
```

Required psql variables: `target_database`, `target_schema`, `migration_owner`,
`api_runtime`, `media_runtime`. Run existing base policies first, then this
supplement. Audit with the existing media-runtime audit script plus
`-v database_worker_authority=true -v native_hub_bindings=true`.
Control can manage credential rows; media gets SELECT only. No runtime gets
permission to delete revocation history. The base schema version is unchanged.

## 3. Switch every media replica to database verification

Set these environment variables in the media workload:

```text
CODINGWORKSPACE_CENTRAL_MEDIA_WORKER_TOKEN_VERIFIER_FACTORY=codingworkspace.media_worker_credentials:from_settings
CODINGWORKSPACE_CENTRAL_MEDIA_WORKER_EXPECTED_ISSUER=urn:codingworkspace:media-workers:prod
CODINGWORKSPACE_CENTRAL_MEDIA_WORKER_EXPECTED_AUDIENCE=codingworkspace-media-worker
CODINGWORKSPACE_MEDIA_WORKER_AUTH_BACKEND=database
```

Remove `CODINGWORKSPACE_MEDIA_WORKER_REGISTRY_FILE`, its registry mount and any
registry-refresher container. This backend refuses file fallback. Control and
all media replicas must use the same primary PostgreSQL database; standby
verification is refused. Finish the rollout of all replicas before testing.

Allow the course's Newcastle operator to reach the control HTTPS origin's
`/api/v1/media-worker-management` route. The instructor route is
`/api/v1/admin/media-worker-management`. Both authenticate every request; no
anonymous route, raw worker key upload, PostgreSQL exposure to Newcastle, or
LTIC-managed publisher secret is required. Keep Authorization out of logs.

## 4. Connect production Hub identity and the student media client

Enable the already-agreed original-server-token registration hook and
`custom:cw:media` / `custom:cw:control` scopes for the AI100 profile, with the
production Hub issuer and roster. Keep the Hub-only registration bearer out of
student pods. Use the production equivalent of the tested staging routes:
control at the approved CW origin, `/api/v1/media/` and `/api/v1/media-control/`
on that same origin routed to media, with worker and registration hosts separate.

Apply the course's [native student overlay](https://github.com/kevinlb1/CodingWorkspace/blob/3f21730ba5874af7546d53a3d26af382166cb917/deploy/ltic-media-activation/student-native-staging.env.example)
using the **actual approved production origin** for all three URL/origin values.
Set `CODINGWORKSPACE_COURSE_AUTH_MODE=hub-server-token` and
`CODINGWORKSPACE_COURSE_MEDIA_ENABLED=1`; remove inherited course-control/media
token-file overrides. Keep unrelated Git/groups/budget feature flags off.

Use the already-promoted student 1.0.22 image, including its preview/log-client
fixes, with the matching `CODINGWORKSPACE_DEPLOYMENT_IMAGE_DIGEST`:

```text
032401129069.dkr.ecr.ca-central-1.amazonaws.com/codingworkspace-notebook@sha256:fd6af3905e4d082e9bf0f873e46a6813f1a4833ef8610ff91f5c47e02c731fa8
```

That student version has the media client but predates the new manager UI.
Course staff can enroll the publisher through the authenticated central API
using an existing verified instructor Hub credential; the next student release
can add the UI without another backend authorization redesign.

Start with a course-staff pod. The course will set initial model policy, enroll
the Newcastle publisher, activate its already-prepared runtime/rotation, and
test an ordinary coding turn plus media generation/artifact retrieval. Initial
control policy must arrive before new coding turns are enabled. After that test,
enable new student spawns; preserve running lab pods until a coordinated restart.

## 5. Enable private instructor logs in the same rollout

The pinned central image and student 1.0.22 already include the diagnostics
receiver/client. The media-authority migration alone does **not** enable log
collection. To give instructors course-wide debugging access, run with the
migration-owner's existing collaboration settings:

```bash
python -m codingworkspace.support_diagnostics migrate
```

Apply the course checkout's
`deploy/kubernetes/central-services/postgres-support-diagnostics-grants.sql`
with `target_database`, `target_schema`, `migration_owner`, and `api_runtime`,
after the base grant policies. Schedule this fixed command daily using the
control API role's existing settings:

```bash
python -m codingworkspace.support_diagnostics purge
```

Connected student pods report bounded, redacted log tails, preview states and
available memory/throttling/OOM counters during normal control synchronization
(normally every 60 seconds). Instructors read them in Admin → Central Control →
Instructor diagnostics. Reads are authenticated and audited; students cannot
read other students' reports. The course will verify an actual instructor read
and student rejection after connection. No logs become public.

These are recent pod snapshots, not a full historical log archive or Kubernetes
monitoring. Hub spawn delays, cluster resource metrics and pods too unhealthy
to report still require LTIC's operator tools. Media can be activated before
this step completes, but course-wide log access must not be reported as working
until a real snapshot and authorized read have succeeded.

[Exact collection limits, grants and instructor API](https://github.com/kevinlb1/CodingWorkspace/blob/3f21730ba5874af7546d53a3d26af382166cb917/deploy/ltic-media-activation/INSTRUCTOR_DIAGNOSTICS.md).

## Course-owned follow-up

Course staff own publisher enrollment/renewal/revocation, worker credentials,
Newcastle supervision and end-to-end application checks. No recurring LTIC
registry updates are needed. Existing student identity remains rooted in Hub;
this change does not let a client assert a CWL or grant itself instructor access.

[Full course handoff, tests and prepared-runtime receipt](https://github.com/kevinlb1/CodingWorkspace/blob/3f21730ba5874af7546d53a3d26af382166cb917/deploy/ltic-media-activation/DATABASE_MEDIA_AUTHORITY.md).

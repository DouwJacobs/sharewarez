# GameLibrary 1.16.3 release verification

Client date: 6 November 2026. Image source commit:
`9461e4a6caba04cfb8ff0a3f271828e84c4216e3` on local `main`.

Published `douwjacobs/gamelibrary:1.16.3` and `douwjacobs/gamelibrary:latest`.
Both remote OCI index manifests were independently inspected and resolve to:

`sha256:fe3a4ac1c90b09475f062109957f724c994aeafd877858040d65e5ddd71ce8cf`

## Release gate

The complete `scripts/quality-gate.sh` passed from a clean detached worktree,
with container build enabled and fresh PostgreSQL 17.6 databases per module:
**2,182 Python tests across 146 modules**. The gate also passed reproducible
lock resolution, dependency audit/check, Ruff, required Mypy, compilation,
95-template accessibility, fresh schema bootstrap/upgrade, single revision head
`20261106_35`, version 1.16.3, Compose validation, image build and packaged compile.
All four JavaScript controller files passed `node --test`: 19 runner cases,
including the favorites file's six internal behavior cases.

The earlier implementation audit's dnspython advisory is resolved: production
and development lockfiles now pin 2.9.2, with a >=2.9.0 input constraint.
The dependency audit found no known vulnerabilities and pip check was clean.
Docker PostgreSQL sessions use UTC; the legacy expiry tests passed in this gate.
Confirm existing deployment database sessions preserve the documented UTC
assumption before upgrading an existing installation.

Clean-checkout testing exposed two test preconditions that had depended on a
locally installed default theme. The settings-concurrency test now supplies its
installed-theme precondition independently; the notification matrix test submits
the portable Site default choice. Their complete modules passed (44 and 26).
These fixes change tests, not application preference behavior. The final gate was
rerun in full. An additional independent clean-checkout preflight covered all 50
modules not reached by the earlier failed gate; none failed.

## Packaged runtime and actual HTTP checks

The exact published image ran against a separately created disposable PostgreSQL
17.6 database, with UID/GID 10001, read-only root, all capabilities dropped,
no-new-privileges, temporary /tmp, and isolated source/library/cache/backup volumes.
Startup copied the default theme successfully. Liveness/readiness passed, and
signed fixture sessions accessed Library, Scan Manager and Download delivery over
real HTTP. A packaged pg_dump backup was created and verified with pg_restore.
Both web and job processes ran. Terminating the job child caused the supervisor
to stop the container with exit 1; restarting it
restored readiness. Every smoke container, network and volume was removed.

Sparse zero-filled fixtures exercised the 2 GiB boundary without allocating a
large client buffer. A real connection was closed after a 2 MiB client prefix,
then resumed through the same authenticated link with Range and If-Range. Each
resumed response was 206 and its original prefix plus remaining bytes matched a
fresh SHA-256 of the immutable representation. The ZIP was prepared by the actual
packaged job worker with a nested asset, launcher and notes.

| Representation | Full response bytes | Reassembled SHA-256 |
| --- | ---: | --- |
| Direct file | 2,147,483,648 | `a7c744c13cc101ed66c29f672f92455547889cc586ce6d44fe76ae824958ea51` |
| Cached ZIP | 2,147,484,265 | `b6d32ad135e6245ef282b2a666bfc02c61aad3ac2a7a70d6f9d1f89452002c8c` |

Both interrupted attempts recorded peer_disconnect and each continuation recorded
completed with HTTP 206 and the selected range length. Server writes can exceed
the client's retained prefix because of buffering; these counts do not confirm
browser disk writes or whole-file completion.

A separate 2 MiB direct response at 0.2 Mbps stayed active after 70 seconds;
its owner heartbeat was 1.46 seconds old.
The first byte arrived after 83.91 seconds,
confirming planned pacing survives the former 60-second stale cutoff with actual
packaged maintenance and web processes running.

These are local Docker ingress checks. No production SQL, running deployment,
NAS mount, TLS proxy, timeout policy or integration credentials were changed.
Deployed-proxy/slow-NAS validation remains an operator deployment check; no claim
is made about the cause of the historical interruption screenshot.

## Reproduction and source publication

The project Python environment ran the full gate with TEST_DB_PORT=55449,
QUALITY_IMAGE_TAG=gamelibrary:release-1.16.3-gate and SKIP_CONTAINER_BUILD=false.
The same clean source used `scripts/build-images.sh`; publication used docker push
for the version tag followed by latest, and both manifests were checked with
`docker buildx imagetools inspect`.

Docker Hub publication does not push GitHub source. Local main contains the
feature, dependency, version and portable-fixture commits; source remains ahead
of origin/main. The original untracked implementation handoff is preserved.

# GameLibrary 1.16.4

Published on 12 November 2026 from source commit
039a9d6e35d0997b95b145cdd563a1caaed7e1a4, identified by Git tag v1.16.4.

Docker Hub tags douwjacobs/gamelibrary:1.16.4, v1.16.4, and latest
were independently inspected and share the OCI index digest
sha256:d22fb46c7a4f4dbfb8a20ff9d53ef53bf07319a4c5d77f23c1e10f58feda37c4.
The published application platform is linux/amd64.

The full local quality gate passed, including dependency locking and audit,
lint, accessibility, focused type checking, 2,182 Python tests in 146 isolated
PostgreSQL modules, migration/version/Compose checks, and the container stage.
All 19 JavaScript runner cases passed. The release image was built from a
git archive of the committed source and carries its source revision label.
A disposable PostgreSQL-backed runtime passed readiness and liveness under
UID/GID 10001, read-only root, dropped capabilities and no-new-privileges,
with both web and job processes running. Its temporary containers and network
were removed. Packaged application and migration compilation passed.

GitHub main and v1.16.4 were pushed, including the 16 earlier local commits.
Authenticated visual verification remains incomplete because the browser
session reached sign-in. No production deployment was performed.

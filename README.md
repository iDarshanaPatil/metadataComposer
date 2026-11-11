# MetadataComposer

A Python-backed configuration and secrets workspace built from BRD.md, RULES.md, and DESIGN.md.

**Status:** implementation ready for local installation and verification. It has not yet passed an end-to-end run. The authoring environment blocked package downloads, Docker access, and PostgreSQL startup. See `VERIFICATION.md` for the checks actually performed.

## Run on your Mac

You need Docker Desktop running and Python 3.12 or newer. Docker builds install the frontend and backend dependencies, so you do not need Node or a separate PostgreSQL installation for this route.

Open Terminal in the extracted `metadatacomposer` folder, then run:

```bash
python3 scripts/setup.py
docker compose up --build
```

The setup script prompts for a password and generates encryption/session keys in `.env`. It never overwrites an existing `.env`.

Once the services are healthy, open **http://localhost:8080** and sign in with the password you chose. Use `localhost`, not `127.0.0.1`, because the allowed browser origin is configured explicitly.

The first build needs internet access and may take a few minutes. Start with sample configuration while you verify the workflows below.

If `docker` is not found on your Mac, try its installed path:

```bash
"$HOME/.docker/bin/docker" compose up --build
```

To stop:

```bash
docker compose down
```

Database data survives this command in the `postgres_data` volume. **Do not add `--volumes` unless you intend to delete the database.** Keep a private backup of `.env` alongside your database backup: losing `MASTER_KEY` makes existing secrets unrecoverable.

## First walkthrough

1. Create an organization, such as `acme`.
2. Create `web-dev`. Its `default` namespace is created automatically.
3. Unlock the app and create a `database` namespace.
4. Add `HOST` as a string, `PORT` as a number, and `PASSWORD` as a secret string.
5. Select **Review & save**. Editing does not write anything before confirmation.
6. Lock the app, reveal `PASSWORD`, and open its History.
7. Create `web-prod`, then copy the `database` namespace into it. Copy refuses to overwrite existing items.
8. Open Tree to inspect the hierarchy. Fold/unfold, zoom, pan, Fit, and Hide variables are available.
9. Open organization Settings to inspect Apps and filtered History.

## Stack and organization

| Area | Implementation |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, synchronous SQLAlchemy 2, psycopg |
| Persistence | PostgreSQL, Alembic migration, database constraints and triggers |
| Secrets | `cryptography` AESGCM, random 12-byte nonce, 256-bit key, contextual associated data |
| Frontend | React 18, TypeScript, Vite, Tailwind and custom CSS |
| Tree | D3 hierarchy/zoom, React-rendered SVG |
| Local hosting | Docker Compose, Nginx frontend proxy, Uvicorn backend |
| Tests | pytest against a separate PostgreSQL database; Vitest draft-diff tests |

- `backend/app/models.py`: data model and row constraints.
- `backend/app/service.py`: transactional saves, copying, validation, encryption orchestration and audit entries.
- `backend/app/main.py`: REST routes, sessions, API errors and masked read/tree responses.
- `backend/app/auth.py`: single-owner password login, signed expiring sessions and CSRF checks.
- `backend/migrations/`: initial schema and cross-row database guards.
- `frontend/src/App.tsx`: default editor, review/copy/create/delete dialogs and settings.
- `frontend/src/Tree.tsx`: read-only zoomable hierarchy.
- `frontend/src/History.tsx`: filtered, paginated audit log.
- `frontend/src/api.ts`: HTTP client and minimal staged-change diffing.

Draft state lives in React hooks. This version uses a small fetch client rather than adding TanStack Query. There is one backend process; no queue, Redis, AI service, or background worker is required.

## Implemented behavior

- Organizations, apps and namespaces, with one protected `default` namespace per app.
- Variable types `string`, `number`, `boolean`, and namespace `ref`.
- Names, key uniqueness, finite numeric values, booleans, byte-length limits and descriptions validated on the server; applicable rules repeated in PostgreSQL.
- Locked-by-default editing, staged additions/changes/removals, Undo, review, Discard, and save shortcut.
- Atomic namespace batch saves including their history; stale revisions return HTTP 409.
- Secret values omitted from normal responses; individual reveal/copy requests are audited.
- AES-256-GCM envelopes bound to org/app/namespace/key. Copy decrypts and re-encrypts under the destination context.
- Same-org namespace and variable copies, with duplicate checks under locks and no overwrites.
- Ref targets restricted to another namespace in the same app; one-level expansion and referenced-namespace deletion protection.
- History retained after variable/namespace deletion, with combined filters and pages of 100 entries.
- Typed organization deletion confirmation; app/org deletion removes the corresponding history as specified.
- Responsive default view, Settings, read-only Tree, and unsaved-navigation confirmation for in-app navigation and page close/reload.

## Tests

Backend integration tests use a separate disposable PostgreSQL database; they never target the normal Compose database:

```bash
docker compose --profile test run --build --rm test
```

Tests refuse to reset a database whose name does not end with `_test`. They cover save rollback and audit rollback, secret masking/reveal/history, destination re-encryption, no-overwrite copies, stale revisions, refs, deletion, CSRF, database guards, and encryption tampering/context mismatch.

Frontend checks, with Node 22 installed:

```bash
cd frontend
npm install
npm test
npm run build
```

The initial archive has no dependency lockfiles because dependency resolution could not finish in the authoring environment. Keep the generated lockfiles after a successful install to make future builds reproducible.

## Development without Docker for the application processes

Keep PostgreSQL in Docker, then run Python and Vite locally:

```bash
# From the project root; run setup first if .env does not exist.
docker compose up -d db
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
alembic upgrade head
ALLOWED_ORIGIN=http://localhost:5173 uvicorn app.main:app --reload --no-access-log
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev -- --host localhost
```

Open http://localhost:5173. Vite proxies `/api` to the local backend. `.env` is loaded relative to the backend working directory; run backend commands from `backend/`.

## API usage

Interactive API documentation is at http://localhost:8000/docs. API routes live under `/api/v1`.

For browser clients, authenticate at `POST /api/auth/login`, retrieve the CSRF token from `GET /api/auth/me`, and supply `X-CSRF-Token` on mutations. The session cookie is HTTP-only and expires after eight hours.

For automated configuration reads, optionally set a long random `READ_API_TOKEN` in `.env`, restart the backend, and pass it as an `Authorization: Bearer ...` header. This is an **owner-level read credential** across all organizations, including explicit secret reveals. It does not authorize writes. Leave it unset if not needed.

Examples of read paths:

```text
GET /api/v1/config/acme/web-dev
GET /api/v1/config/acme/web-dev?refs=PORT,database.HOST
GET /api/v1/config/acme/web-dev?expand=1
GET /api/v1/config/acme/web-dev?refs=database.PASSWORD&reveal=true
```

Responses contain `{ "config": { ... }, "missing": [...] }`. Non-ref values remain strings, matching the text-backed model. Masked secrets are `null`. Ref values are `{ "$ref": "namespace" }` unless one-level expansion is requested. Each revealed secret is logged before the response is returned, including refs expanded into secrets.

Batch save:

```text
POST /api/v1/variables/{org}/{app}/{namespace}/batch
{ "revision": 0, "changes": [{ "op": "put", "key": "PORT", "value": "5432", "type": "number" }] }
```

Get the current revision from the namespace variable-list endpoint. Omitted fields retain their stored values; explicit null is rejected. Individual PUT requests take the same editable fields plus `revision` in the body. Individual DELETE requests require `?revision=N`. Errors are `{ "error": "message" }`.

## Scope decisions and remaining work

- **Single-owner authentication:** all operations belong to the configured owner. Administrator/developer/reviewer membership and role-based permissions are not implemented; the requirements did not define that model. UI locking prevents accidental editing and is not authorization.
- **Local deployment only:** no public hosting or production claim. Before team use, add membership/roles and scoped machine credentials, key rotation, durable distributed login throttling, and verify the full suite. Production also needs HTTPS, `COOKIE_SECURE=true`, correct `ALLOWED_ORIGIN`, and managed secrets/backups.
- **UI differences:** system font fallbacks are used instead of downloaded Geist fonts. Fit/zoom are immediate rather than animated. Browser QA and accessibility testing remain unverified.
- **Database limitation:** PostgreSQL cannot inspect the plaintext type or size of an encrypted value while the key remains outside the database. Python enforces those rules before encryption; PostgreSQL enforces envelope and structural constraints.
- **Copying refs:** the target namespace must already exist in the destination app; otherwise the entire copy fails. Copying never follows refs or copies missing referenced namespaces implicitly.
- **History retention:** history is append-only under normal writes and deletes, with controlled FK maintenance. A database administrator can still alter or truncate tables; this is not a tamper-proof external audit service.
- **Migration baseline:** the initial migration creates tables from the current model metadata. Freeze that baseline into explicit Alembic table operations before evolving the schema in subsequent releases.

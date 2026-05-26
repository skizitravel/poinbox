# MountainGoat Single-Tenant Deployment

This deployment path is intended for the first customer instance: one deployed app, one persistent database/storage volume, and Admin-managed integrations.

## What Goes To GitHub

- Application code and static assets
- Dockerfile and deployment examples
- `.env.example` and `.env.production.example`
- Documentation

## What Must Not Go To GitHub

- `.env.local` or real production env files
- SQLite runtime databases
- Uploaded purchase orders and downloaded email attachments
- OAuth access or refresh tokens
- OpenAI API keys, OAuth client secrets, ERP tokens, or customer documents
- Runtime logs

## Required Production Settings

Set these as platform secrets or environment variables:

```text
APP_ENV=production
APP_BASE_URL=https://app.your-domain.com
DATABASE_PATH=/data/db.sqlite
STORAGE_DIR=/data/storage
SAMPLES_DIR=/data/samples/inbox
TEST_CORPUS_DIR=/data/samples/test-corpus
ENCRYPTION_KEY=<stable long random secret>
INITIAL_ADMIN_EMAIL=<admin email>
INITIAL_ADMIN_NAME=<admin name>
INITIAL_ADMIN_PASSWORD=<first-run admin password>
SESSION_COOKIE_SECURE=1
```

Keep `ENCRYPTION_KEY` stable for the life of the instance. Changing it will prevent the app from decrypting stored Admin-entered secrets.

## Persistent Volume

Mount a persistent volume at `/data`. The Dockerfile defaults the database and runtime storage to:

```text
/data/db.sqlite
/data/storage
/data/samples/inbox
/data/samples/test-corpus
```

Back up `/data` regularly. SQLite is acceptable for a controlled first-customer pilot, but future multi-customer SaaS should move to managed Postgres and object storage.

## First Boot

1. Deploy the container with the production environment variables.
2. Visit `https://app.your-domain.com/health` and confirm it returns `ok`.
3. Log in with `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD`.
4. Create operator users under Admin > Users & Access.
5. Configure OpenAI and Gmail/Outlook under Admin > Testing.
6. Restart the app and confirm the integration status remains configured.

Admins configure secrets once. Operators process purchase orders through the PO Dashboard and Exceptions Queue without seeing integration setup or raw secrets.

## Local Docker Run

```powershell
docker build -t mountaingoat .
docker run --rm -p 8000:8000 -v ${PWD}\.runtime-data:/data --env-file .env.production.example mountaingoat
```

Replace placeholder values before using this for a real environment.

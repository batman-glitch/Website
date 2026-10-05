# Blessson — Audio Engineer Portfolio

A responsive portfolio with a private enquiry inbox. The live site accepts project enquiries into a PostgreSQL database and keeps administrator access behind password authentication. The local development server uses SQLite and is bound to `127.0.0.1` only.

## Local development

From this folder, run:

    python3 server.py

On first run, the server asks you to create an administrator email and password in the terminal. Use a passphrase at least 14 characters long. The password is stored only as a salted PBKDF2-SHA256 hash. The local database and session secret live in `data/`, with owner-only file permissions.

- Portfolio: `http://127.0.0.1:8787/`
- Private inbox: `http://127.0.0.1:8787/admin`

The dashboard includes inbox totals, full-inbox search, status and service filters, date sorting, pagination, direct email replies, workflow updates, and filtered CSV export. Local enquiries are stored in `data/portfolio.sqlite3`.

## Vercel deployment

The repository serves the public static files from `Website/cr/outputs` and runs the Python handlers in the root `api/` directory. The hosted admin is available at `/admin`; its requests use secure, HttpOnly session cookies, CSRF protection, server-side session records, login throttling, and a persistent PostgreSQL database.

Connect a PostgreSQL database to the Vercel project and make sure it provides `DATABASE_URL`. Add these production environment variables in Vercel:

- `ADMIN_EMAIL`: the administrator account email.
- `ADMIN_INITIAL_PASSWORD_HASH`: the one-time password pre-hashed with salted PBKDF2-SHA256 (600,000 iterations). The first successful sign-in requires choosing a replacement; the plaintext password is never stored in Vercel or the database.
- `ADMIN_SESSION_SECRET`: a randomly generated secret with at least 32 characters, used to sign rate-limit keys.

Keep these values in Vercel's encrypted environment-variable store. Never place database credentials or passwords in the frontend, repository, or local logs. Do not use SQLite for hosted functions because serverless storage is not durable.

The public showcase cards are concept studies. Replace them with confirmed release credits and audio links when those are ready.

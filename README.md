# Audio engineer portfolio

This is a local full-stack starter. It uses the existing HTML frontend, a small Python standard-library API, and SQLite for project enquiries.

## Run locally

From this folder, run:

    python3 server.py

The server listens only on http://127.0.0.1:8787. On first start, it prints an admin access token and saves it in data/.admin-token with owner-only file permissions.

- Portfolio: http://127.0.0.1:8787/
- Private inbox: http://127.0.0.1:8787/admin

Paste the token into the inbox sign-in screen. The token stays in the current browser tab. Enquiries are stored in data/portfolio.sqlite3; the admin screen can search, filter, update status, and export CSV. Use the email link on an enquiry to reply.

If you open index.html directly as a file, the enquiry form falls back to preparing an email draft. Start the local server to save enquiries into the inbox.

## Before public launch

This server is intentionally bound to the local machine and is a development starter. Public hosting needs a production web server, HTTPS, persistent backups, and a configured email notification/reply workflow. Replace the demo identity, contact email, and sample credits with confirmed details. Real audio samples can be added once supplied.

# Blessson — Audio Engineer Portfolio

A responsive, static portfolio with an optional local enquiry inbox. The live Vercel site serves the portfolio and prepares an email draft if an online form endpoint is unavailable. It does not claim to store public enquiries.

## Run the local inbox

From this folder, run:

    python3 server.py

The local server listens only on `http://127.0.0.1:8787`.

- Portfolio: `http://127.0.0.1:8787/`
- Private local inbox: `http://127.0.0.1:8787/admin`

On first start, the server prints a one-time admin token and saves it in `data/.admin-token` with owner-only file permissions. Keep the token private. Enquiries submitted to the local server are stored in `data/portfolio.sqlite3`. The inbox supports search, status updates, direct email replies, and CSV export.

Opening `index.html` as a local file or visiting the static Vercel deployment does not connect to the local database. If no hosted enquiry endpoint is available, the form creates a ready-to-send email draft addressed to `blessonkondeti@gmail.com`.

## Hosting and data

`server.py` and the SQLite inbox are for local development. Vercel deploys the public site as static files, so the SQLite database and private inbox do not run there. Before collecting enquiries into an online dashboard, connect a durable database and a trusted email provider, configure their private environment variables in Vercel, and add an authenticated online admin. Do not put database credentials or email API keys in the public frontend.

The showcase cards are marked as concept studies. Replace them with confirmed release credits and audio links when those are ready.

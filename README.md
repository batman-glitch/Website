# Blessson — Audio Engineer Portfolio

The portfolio is in [Website/cr/outputs](Website/cr/outputs/). The Vercel project serves its static files and runs the password-protected enquiry backend as Python Functions backed by Neon Postgres.

## Local preview and inbox

```sh
cd Website/cr/outputs
python3 server.py
```

The local server listens on `127.0.0.1:8787`. On first run, create a local administrator passphrase in the terminal. Local inquiry data and the session secret are kept in the ignored `Website/cr/outputs/data/` folder with owner-only permissions.

## Production setup

The Vercel project is connected to Neon Postgres and the admin route is `/admin`. Configure the production environment variables `ADMIN_EMAIL`, `ADMIN_INITIAL_PASSWORD_HASH`, and `ADMIN_SESSION_SECRET` in Vercel. The one-time initial password is represented by a salted PBKDF2-SHA256 hash and must be changed on first sign-in. Never commit database connection strings or credentials.

See [the website README](Website/cr/outputs/README.md) for local and hosting details.

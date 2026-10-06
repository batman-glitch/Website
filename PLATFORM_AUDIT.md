# Unified studio platform — implementation audit

## Implemented

- Shared `/login` authenticates with Django, then uses the database user's role to redirect.
- Public `/register` always creates a CLIENT. Permission fields in requests are rejected.
- Public header has Sign in/Register; authenticated accounts receive a Dashboard link from the backend. The B logo links home.
- Client dashboard: project progress/dates, own enquiries and responses, private files, conversations, profile, password change and logout.
- Custom admin dashboard: overview, projects, enquiries, client accounts, services, portfolio media, files, messages, testimonials and public settings.
- Canonical custom admin route: `/dashboard/admin/`; `/admin/dashboard/` is an authenticated alias. Django's internal management stays at `/admin/` with the same login.
- API authorization checks authentication, role and ownership independently of HTML pages.
- Existing admin hashes/MFA and portfolio content import once into additive Django tables. Legacy guest enquiries are never assigned by matching email alone.
- Argon2 password hashing, secure production session/CSRF cookies, CSRF protection, request throttling and private file encryption.
- Public portfolio content refreshes across tabs after saves; other open visitors refresh periodically.

## Verified locally

23 automated checks cover role escalation, login redirects, dashboard rendering, ownership, API restrictions, encrypted uploads/downloads, CSRF, deactivation, enquiry conversion, public service edits, password changes, password-reset link single use and native Django admin account creation.

Django system check, migration consistency check and frontend asset build pass.

## Operational limits

- Private project attachments currently use encrypted PostgreSQL storage, capped at 3 MB to remain below Vercel function request limits. Large sessions can be shared as secure transfer links in Messages.
- Public portfolio covers support 12 MB and audio previews 250 MB through direct Blob uploads; these are explicitly public portfolio media.
- Password reset implementation remains available for a future email setup. By the owner's latest instruction, email setup is excluded; the login recovery link stays hidden without a configured provider. Existing credentials and authenticated password changes work.
- Browser visual verification is pending because Chrome exits before launch in this execution environment. Automated backend checks do not substitute for visual/browser upload checks.
- A private Blob store creation attempt reported an existing-token connection conflict, then an existing store name. Its connection is unverified and the application does not depend on it.

## Deployment

Required production variables: `DATABASE_URL`, stable `DJANGO_SECRET_KEY`, `BLOB_READ_WRITE_TOKEN` for public portfolio media. Preserve `ADMIN_MFA_ENCRYPTION_KEY` for imported MFA accounts. Do not rotate the Django secret without a plan to migrate encrypted private attachments.

Build runs additive migrations, the idempotent legacy import, asset bundling and Django static collection. Keep legacy tables for rollback. A deployment build and live route checks must pass before promotion; live upload requires a signed-in browser check.

Create additional administrators only with Django management or the authorized internal admin. Never use public registration to create administrators.

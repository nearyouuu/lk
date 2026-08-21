# License Setup

1. Generate keys once on your side:
   - `python scripts/generate_license_keys.py`

2. Keep files separate:
   - keep `license_private.pem` only on your machine
   - ship only `license_public.pem` with the product

3. Ask the client for the server fingerprint:
   - `GET /license/fingerprint`
   - the production Compose mounts the host `/etc/machine-id`, so container recreation does not change it

4. Issue a license:
   - `python scripts/issue_license.py --customer "ООО Ромашка" --fingerprint "sha256:..." --license-id "LIC-2026-000001" --tariff standard --days 365 --domain ddt.donstu.ru`

5. Give the client:
   - `license.lic`
   - `license_public.pem`

6. Put both files next to the project root on the client server.

7. Check status:
   - `GET /license/status`

Notes:
- The app verifies the signature using `license_public.pem`.
- The license is bound to `hardware_fingerprint` when that field is set.
- The main feature set is derived from the tariff:
  - `basic`: admin panel, schedule, grades, attendance
  - `standard`: `basic` + portfolio, user page, applications, materials, tests
  - `premium`: `standard` + domain email, customization
- You can still add custom extras with repeated `--feature ...`.
- Dates must be ISO-8601, for example `2027-06-23T10:00:00Z`.
- Do not ship `license_private.pem` to the client.
- An offline signed license cannot be revoked before `expires_at` and is vulnerable to system-clock rollback by a client with root access. Use short-lived licenses plus an online activation/heartbeat service when immediate revocation is a contract requirement.

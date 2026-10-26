# ARYAN TEAM Premium Website

Premium dark/mobile-first Flask app built from the requested admin/user/staff panel concept. It includes registration/login, user wallet dashboard, admin dashboard, ZapUPI key and minimum top-up settings, payment order creation, webhook receiver, order-status verification, and SQLite storage.

## Run locally (Android-friendly via Replit / Render / Railway)
1. Upload this folder/repository to a Python web host.
2. Install dependencies: `pip install -r requirements.txt`
3. Set environment variables:
   - `SECRET_KEY` = a long random secret
   - `ADMIN_EMAIL` = `armanmalikh762@gmail.com`
   - `ADMIN_PASSWORD` = set a strong password (the requested `aryan123` is weak; change it before public deployment)
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Open the deployed site. Register normal user accounts from **Create account**. The admin account is created on first startup.
6. Sign in to admin using the configured admin email/password. In **Gateway & website settings**, paste your ZapUPI key and save.
7. In ZapUPI dashboard, set webhook URL to `https://YOUR-DOMAIN/webhook/zapupi`. The app also sends this URL on each order.
8. Test with a small amount before using real payments.

## Important
- ZapUPI backend API endpoints follow https://zapupi.com/docs: `POST https://pay.zapupi.com/api/create-order` and `POST https://pay.zapupi.com/api/order-status`.
- Wallet credit is idempotent and only occurs after a successful webhook plus a server-side order-status check and amount match. The frontend never credits balance.
- Set `DATABASE_PATH` to persistent storage on hosting; ephemeral disks can lose SQLite data after redeploys. For production, use persistent disk/managed PostgreSQL.
- Never put the ZapUPI key in HTML/JavaScript. Use HTTPS and a strong `SECRET_KEY`/admin password.
- ZapUPI docs describe webhook status values `Success`/`Failed`; provider response shape can vary by account. Confirm real test responses in your ZapUPI dashboard. If your order-status response nests fields, adapt `zapupi_webhook()` to that exact response.
- Your uploaded Firebase Rule.txt permits any authenticated user to write many sensitive paths. Do not deploy those rules as-is for a public money-handling site. This Flask project does not depend on Firebase.
- Original uploaded HTML pages are kept in `legacy_reference/` for reference; the active pages in this project use the new Flask backend.

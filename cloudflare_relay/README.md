# Telegram relay (Cloudflare Worker)

Forwards Telegram Bot API calls via Cloudflare when `api.telegram.org` is blocked on
the direct connection. The app points at it through the `TELEGRAM_API_BASE` env var;
everything else (Kite/market data) stays on the direct connection.

## Deploy (dashboard, ~3 min, no install)

1. https://dash.cloudflare.com → **Workers & Pages** → **Create** → **Create Worker**.
2. Name it (e.g. `tg-relay`), **Deploy**, then **Edit code**.
3. Paste the contents of `worker.js`, **Deploy**.
4. Worker **Settings → Variables → Add variable**:
   - Name: `RELAY_SECRET`
   - Value: a long random string (generate with `python -c "import secrets;print(secrets.token_urlsafe(24))"`)
   - Click **Encrypt**, then **Save**.
5. Note the Worker URL: `https://tg-relay.<your-subdomain>.workers.dev`.

## Point the app at it

In the project `.env`:

```
TELEGRAM_API_BASE=https://tg-relay.<your-subdomain>.workers.dev/r/<RELAY_SECRET>
```

(no trailing slash). Then restart the live agents so they reload config + `.env`.

## Verify

```bash
./venv/bin/python -c "from telegram_notifier import TelegramNotifier; print('sent:', TelegramNotifier().send_test_message())"
```

Expect `sent: True` and a test message in both channels.

## Notes

- The token still travels in the request path, but only as far as Cloudflare (HTTPS) —
  not to any anonymous third party. The `/r/<secret>/` prefix stops the Worker being an
  open relay.
- Free tier = 100k requests/day, far above alert volume.
- If Cloudflare ever gets blocked too, unset `TELEGRAM_API_BASE` to fall back to direct.

/**
 * Telegram Bot API relay (Cloudflare Worker).
 *
 * Forwards requests to https://api.telegram.org when that host is blocked on the
 * direct connection (e.g. ISP-level block). The Mac sends to:
 *
 *     https://<worker>.workers.dev/r/<RELAY_SECRET>/bot<TOKEN>/sendMessage
 *
 * The Worker validates the /r/<secret>/ prefix (so it isn't an open relay), strips
 * it, and forwards the rest verbatim to api.telegram.org. Method, body, query string
 * and the Telegram response status/headers (incl. Retry-After) are preserved.
 *
 * RELAY_SECRET is set as a Worker secret/var — never hard-coded here.
 */
export default {
  async fetch(request, env) {
    if (!env.RELAY_SECRET) {
      return new Response("relay not configured", { status: 500 });
    }

    const url = new URL(request.url);
    const prefix = `/r/${env.RELAY_SECRET}/`;
    if (!url.pathname.startsWith(prefix)) {
      return new Response("forbidden", { status: 403 });
    }

    // Keep the leading slash of the forwarded path: /bot<token>/sendMessage
    const tgPath = url.pathname.slice(prefix.length - 1);
    const tgUrl = `https://api.telegram.org${tgPath}${url.search}`;

    const init = { method: request.method, headers: {} };
    const ct = request.headers.get("content-type");
    if (ct) init.headers["content-type"] = ct;
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    const resp = await fetch(tgUrl, init);
    // Pass through Telegram's status, headers (Retry-After) and body unchanged.
    return new Response(resp.body, resp);
  },
};

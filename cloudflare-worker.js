/**
 * ULTRA GAMING VPN — Cloudflare Worker relay
 *
 * A second entry point on Cloudflare's network. Tunnels that reach the
 * worker are relayed to the Railway deployment over a REAL WebSocket bridge
 * (not a plain fetch()), so VLESS/VMess/Trojan tunnels survive the hop.
 *
 * Deploy:
 *   1. Cloudflare dashboard -> Workers & Pages -> Create Worker
 *   2. Paste this file, Deploy
 *   3. Settings -> Variables:
 *        UPSTREAM     your-app.up.railway.app   (no https://)
 *        PATH_PREFIX  the transport prefix shown on the panel's Settings page
 *        FALLBACKS    optional comma-separated backup hostnames
 *   4. Verify:  https://<worker>/ping       -> pong
 *               https://<worker>/__status   -> JSON with "reachable": true
 *   5. Put the worker hostname into CF_WORKER_HOST in Railway, redeploy.
 */

// Must stay in sync with app/paths.py — the tests compare these against
// the panel's own suffix list.
const SUFFIXES = ["/xhttp", "/vless", "/upgrade", "/vmess", "/trojan"];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/ping") {
      return text("pong");
    }
    if (url.pathname === "/__status") {
      return statusResponse(env);
    }

    const hosts = configuredHosts(env);
    if (!hosts.length) {
      return json({ error: "UPSTREAM is not configured on the worker" }, 500);
    }

    // Strip the worker-side prefix (if any) before matching suffixes. The
    // panel derives its prefix from PATH_SECRET; the worker just needs the
    // same value in PATH_PREFIX.
    let path = url.pathname;
    const prefix = String(env.PATH_PREFIX || "").trim().replace(/\/+$/, "");
    if (prefix && (path === prefix || path.startsWith(prefix + "/"))) {
      path = path.slice(prefix.length) || "/";
    }

    // XHTTP packet-up uploads go to /<prefix>/xhttp/<uuid>/<seq>, so the
    // match must cover subpaths, not just the bare suffix.
    const rest = path;
    for (const s of SUFFIXES) {
      if (rest === s || rest.startsWith(s + "/")) {
        return relayRequest(request, hosts, url);
      }
    }

    // Everything else (panel, portal, subscriptions, decoy site) is proxied
    // unchanged, so the worker hostname behaves like the real one.
    return relayRequest(request, hosts, url);
  },
};

function configuredHosts(env) {
  const out = [];
  for (const raw of [env && env.UPSTREAM, env && env.FALLBACKS]) {
    for (const piece of String(raw || "").split(",")) {
      const host = piece.trim()
        .replace(/^https?:\/\//i, "")
        .replace(/\/.*$/, "");
      if (host && out.indexOf(host) === -1) {
        out.push(host);
      }
    }
  }
  return out;
}

async function relayRequest(request, hosts, url) {
  const isWs = String(request.headers.get("Upgrade") || "")
    .toLowerCase() === "websocket";

  let lastError = "no upstream attempted";
  for (let i = 0; i < hosts.length; i++) {
    const host = hosts[i];

    // Failover is only allowed while NOTHING has been committed to the
    // visitor. Once the upstream socket is accepted, or a streamed response
    // head has been forwarded, replaying the request elsewhere would
    // corrupt or duplicate the session — so we stop trying after that.
    let canFailover = true;

    const target = "https://" + host + url.pathname + url.search;
    try {
      const init = {
        method: request.method,
        headers: request.headers,
        redirect: "manual",
      };
      if (isWs) {
        // Upgrade header rides along in request.headers; no body.
      } else if (request.method !== "GET" && request.method !== "HEAD") {
        // duplex = "half" is what keeps XHTTP packet-up uploads STREAMING
        // through the worker instead of being buffered whole.
        init.body = request.body;
        init.duplex = "half";
      }

      const upstreamResp = await fetch(target, init);

      if (isWs) {
        const upstream = upstreamResp.webSocket;
        if (canFailover && (!upstreamResp.ok || !upstream)) {
          lastError = "upstream refused the websocket upgrade";
          continue;
        }
        canFailover = false;
        return bridgeWebSocket(upstreamResp);
      }

      // Non-WS: forward the streamed body as-is.
      canFailover = false;
      return new Response(upstreamResp.body, {
        status: upstreamResp.status,
        statusText: upstreamResp.statusText,
        headers: upstreamResp.headers,
      });
    } catch (err) {
      lastError = String((err && err.message) || err);
      if (!canFailover) {
        break;
      }
    }
  }
  return json({ error: "all upstreams failed", detail: lastError }, 502);
}

async function bridgeWebSocket(upstreamResp) {
  const pair = new WebSocketPair();
  const visitor = pair[0];
  const webSocket = upstreamResp.webSocket;

  // Without accept() on BOTH ends the relayed socket stays paused and the
  // tunnel hangs forever — this is the bug the previous fetch()-only
  // version had.
  webSocket.accept();
  visitor.accept();

  webSocket.addEventListener("message", (event) => {
    if (visitor.readyState === 1) {
      visitor.send(event.data);
    }
  });
  visitor.addEventListener("message", (event) => {
    if (webSocket.readyState === 1) {
      webSocket.send(event.data);
    }
  });

  const closeBoth = () => {
    try { webSocket.close(); } catch (e) {}
    try { visitor.close(); } catch (e) {}
  };
  webSocket.addEventListener("close", closeBoth);
  visitor.addEventListener("close", closeBoth);

  return new Response(null, { status: 101, webSocket: visitor });
}

async function statusResponse(env) {
  const hosts = configuredHosts(env);
  let reachable = false;
  let checked = null;
  if (hosts.length) {
    checked = hosts[0];
    try {
      const r = await fetch("https://" + hosts[0] + "/health",
                            { redirect: "manual" });
      reachable = r.ok;
    } catch (e) {
      reachable = false;
    }
  }
  return json({
    upstream: hosts[0] || null,
    fallbacks: hosts.slice(1),
    prefix: String((env && env.PATH_PREFIX) || ""),
    suffixes: SUFFIXES,
    reachable: reachable,
    checked: checked,
  });
}

function text(body, status) {
  return new Response(body, {
    status: status || 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function json(data, status) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

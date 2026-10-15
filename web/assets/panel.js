/* ULTRA GAMING VPN — admin panel */
(function () {
  "use strict";

  // Baked into this file at build time. Compared against the version the
  // server reports so a stale cached asset is detected, not guessed at.
  var ASSET_VERSION = "3.7.0";

  /** start.sh appends "-<buildid>"; only the semver part is comparable. */
  function baseVer(v) { return String(v).split("-")[0]; }
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var t = UG.t, esc = UG.esc, api = UG.api;

  var S = {
    page: "dash", boot: null, stats: null, users: [], es: null,
    rx: [], tx: [], cpu: [], MAX: 70, hist: [], window: "24h",
    profile: "balanced", raceRunning: false, lastAch: {}
  };

  // ══ i18n ════════════════════════════════════════════════════════════
  function applyI18n() {
    $$("[data-i]").forEach(function (el) { el.textContent = t(el.dataset.i); });
    document.body.setAttribute("dir", UG.lang() === "fa" ? "rtl" : "ltr");
    if (S.boot) render();
  }
  addEventListener("ug:lang", applyI18n);

  // ══ LOGIN ═══════════════════════════════════════════════════════════
  $("#loginForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = $("#loginBtn"), err = $("#loginErr");
    btn.disabled = true; btn.innerHTML = '<span class="sp"></span>';
    err.classList.add("hide");
    fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("#lu").value, password: $("#lp").value })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.d.error || "login failed");
        UG.setToken(res.d.token); start();
      })
      .catch(function (e) {
        err.textContent = e.message; err.classList.remove("hide");
        btn.disabled = false; btn.textContent = t("login");
      });
  });

  $("#logoutBtn").addEventListener("click", function () {
    UG.setToken(""); if (S.es) S.es.close(); location.reload();
  });

  $("#burger").addEventListener("click", function () { $("#side").classList.toggle("open"); });

  // ══ BOOT ════════════════════════════════════════════════════════════
  function showVersion() {
    var el = $("#verTag");
    var sv = S.boot && S.boot.version;
    if (!el || !sv) return;
    el.textContent = "v" + sv;
    if (baseVer(ASSET_VERSION) !== sv) {
      el.textContent = "v" + sv + " ⚠";
      el.style.color = "var(--amber)";
      UG.toast(
        "⚠️ Cached panel is out of date<br>" +
        "<small>loaded v" + ASSET_VERSION + ", server is v" + sv +
        "</small><br><button class='btn sm' onclick='UG.hardReload()' " +
        "style='margin-top:7px'>Reload now</button>", "err", 15000);
    }
  }

  function start() {
    $("#login").classList.add("hide");
    $("#app").classList.remove("hide");
    UG.particles($("#particles"));
    applyI18n();
    load().then(function () { showVersion(); connect(); nav("dash"); });
  }

  function load() {
    return api("/api/bootstrap").then(function (b) {
      S.boot = b; S.users = b.users || []; S.stats = b.stats || null;
      return b;
    }).catch(function (e) { UG.toast(esc(e.message), "err"); });
  }

  function refreshUsers() {
    return api("/api/users").then(function (u) {
      S.users = u;
      if (S.page === "users" || S.page === "dash") render();
    });
  }

  // ══ SSE ═════════════════════════════════════════════════════════════
  function connect() {
    if (S.es) S.es.close();
    S.es = new EventSource("/api/stream?t=" + encodeURIComponent(UG.token()));
    S.es.onmessage = function (e) {
      try {
        var s = JSON.parse(e.data);
        S.stats = s;
        S.rx.push(s.network.rx_speed); if (S.rx.length > S.MAX) S.rx.shift();
        S.tx.push(s.network.tx_speed); if (S.tx.length > S.MAX) S.tx.shift();
        S.cpu.push(s.cpu); if (S.cpu.length > S.MAX) S.cpu.shift();
        $("#livePill").classList.remove("off");
        paintLive();
      } catch (_) { }
    };
    S.es.onerror = function () {
      $("#livePill").classList.add("off");
      S.es.close(); setTimeout(connect, 4000);
    };
  }

  // ══ NAV ═════════════════════════════════════════════════════════════
  var TITLES = {
    dash: ["dashboard", "Real-time monitoring"],
    users: ["users", "Accounts, quotas and ranks"],
    analytics: ["analytics", "History, heatmap and leaderboard"],
    race: ["race", "Find the fastest route"],
    games: ["gameping", "Latency to real game servers"],
    locations: ["locations", "Country exits — slow, not for gaming"],
    trials: ["trials", "Self-service trial accounts"],
    console: ["console", "Direct server commands"],
    settings: ["settings", "Runtime configuration"]
  };

  function nav(p) {
    S.page = p;
    $$(".navlink").forEach(function (a) { a.classList.toggle("on", a.dataset.page === p); });
    $("#pageTitle").textContent = t(TITLES[p][0]);
    $("#pageSub").textContent = TITLES[p][1];
    $("#side").classList.remove("open");
    render();
    if (p === "analytics") loadHistory();
    if (p === "locations") loadLocations();
  }
  $$(".navlink").forEach(function (a) {
    a.addEventListener("click", function () { nav(a.dataset.page); });
  });

  // ══ RENDER ══════════════════════════════════════════════════════════
  function render() {
    var el = $("#pages");
    if (S.page === "dash") el.innerHTML = viewDash();
    else if (S.page === "users") el.innerHTML = viewUsers();
    else if (S.page === "analytics") el.innerHTML = viewAnalytics();
    else if (S.page === "race") el.innerHTML = viewRace();
    else if (S.page === "games") el.innerHTML = viewGames();
    else if (S.page === "locations") el.innerHTML = viewLocations();
    else if (S.page === "trials") { el.innerHTML = viewTrials(); loadTrials(); }
    else if (S.page === "console") { el.innerHTML = viewConsole(); initConsole(); }
    else if (S.page === "settings") el.innerHTML = viewSettings();
    paintLive();
    if (S.page === "analytics") { paintHistory(); paintHeatmap(); }
  }

  // ── dashboard ──────────────────────────────────────────────────────
  function viewDash() {
    var s = S.stats || {}, m = s.memory || {}, n = s.network || {};
    return '' +
      '<div class="row4">' +
        card("cpu", "cpuVal", "0", "%", "cpuBar", "f-cpu", "cpuSub") +
        card("ram", "ramVal", "0", "%", "ramBar", "f-ram", "ramSub") +
        '<div class="card"><div class="lbl">' + t("sessions") + '</div>' +
          '<div class="val" id="connVal">0<span class="u">live</span></div>' +
          '<div class="sub" id="connSub">—</div></div>' +
        '<div class="card"><div class="lbl">' + t("uptime") + '</div>' +
          '<div class="val" id="upVal" style="font-size:21px">—</div>' +
          '<div class="sub" id="upSub">' + esc((S.boot && S.boot.host) || "") + '</div></div>' +
      '</div>' +

      '<div class="row21">' +
        '<div class="card"><div class="title">' + t("netspeed") +
          '<div class="grow"></div>' +
          '<span style="color:var(--neon);font-family:var(--mono);font-size:13px" id="rxNow">0</span>' +
          '<span style="color:var(--neon2);font-family:var(--mono);font-size:13px" id="txNow">0</span>' +
          '</div><canvas class="graph" id="netG"></canvas></div>' +
        '<div class="card"><div class="title">' + t("score") + '</div>' +
          '<div class="gauge"><canvas id="scoreG"></canvas>' +
          '<div class="info"><b id="scoreV">—</b><p id="scoreT">' + t("loading") + '</p></div></div></div>' +
      '</div>' +

      '<div class="row2">' +
        '<div class="card"><div class="title">' + t("totaltraffic") + '</div>' +
          '<div class="kv"><b>↓ ' + t("download") + '</b><span id="rxT" style="color:var(--neon)">—</span></div>' +
          '<div class="kv"><b>↑ ' + t("upload") + '</b><span id="txT" style="color:var(--neon2)">—</span></div>' +
          '<div class="kv"><b>Peak ↓</b><span id="pkRx">—</span></div>' +
          '<div class="kv"><b>Peak ↑</b><span id="pkTx">—</span></div>' +
          '<div class="kv"><b>Load avg</b><span id="loadV">—</span></div>' +
        '</div>' +
        '<div class="card"><div class="title">' + t("topusers") + '</div>' +
          '<div id="topBox">' + topList() + '</div></div>' +
      '</div>' +

      '<div class="card"><div class="title">' + t("events") +
        '<div class="grow"></div><button class="btn sm dim" id="evR">↻</button></div>' +
        '<div id="evBox" style="max-height:230px;overflow-y:auto"></div></div>';
  }

  function card(lbl, vid, v, u, bid, bcls, sid) {
    return '<div class="card"><div class="lbl">' + t(lbl) + '</div>' +
      '<div class="val" id="' + vid + '">' + v + '<span class="u">' + u + '</span></div>' +
      '<div class="track"><div class="fill ' + bcls + '" id="' + bid + '" style="width:0%"></div></div>' +
      '<div class="sub" id="' + sid + '">—</div></div>';
  }

  function topList() {
    var us = S.users.slice().sort(function (a, b) {
      return (b.used_total || 0) - (a.used_total || 0);
    }).slice(0, 6);
    if (!us.length) return '<div class="empty"><span class="em">👾</span>' + t("noplayers") + '</div>';
    return us.map(function (u, i) {
      var r = u.rank || {};
      return '<div class="kv"><b>' + (i + 1) + '. ' + esc(u.username) +
        ' <span class="rank" style="color:' + esc(r.color || "#888") + '">' +
        esc(r.icon || "") + ' ' + esc(r.name || "") + '</span></b>' +
        '<span>' + UG.bytes(u.used_total || 0) + '</span></div>';
    }).join("");
  }

  // ── live paint ─────────────────────────────────────────────────────
  function paintLive() {
    var s = S.stats; if (!s) return;
    var m = s.memory || {}, n = s.network || {};

    if ($("#xrayPill")) {
      var xp = $("#xrayPill");
      xp.classList.toggle("off", !s.xray);
      xp.lastElementChild.textContent = t("xray") + " " + (s.xray ? t("online") : t("offline"));
    }
    if (S.page !== "dash") return;

    var cv = $("#cpuVal");
    if (cv) {
      UG.countTo(cv, s.cpu, function (v) { return v.toFixed(1) + '<span class="u">%</span>'; });
      $("#cpuBar").style.width = Math.min(100, s.cpu) + "%";
      $("#cpuSub").textContent = "load " + (s.load || []).map(function (x) { return x.toFixed(2); }).join(" · ");
    }
    var rv = $("#ramVal");
    if (rv) {
      UG.countTo(rv, m.percent || 0, function (v) { return v.toFixed(1) + '<span class="u">%</span>'; });
      $("#ramBar").style.width = Math.min(100, m.percent || 0) + "%";
      $("#ramSub").textContent = (m.used_mb || 0) + " / " + (m.total_mb || 0) + " MB";
    }
    if ($("#connVal")) {
      $("#connVal").innerHTML = (s.connections || 0) + '<span class="u">live</span>';
      var pp = s.per_port || {}, parts = [];
      Object.keys(pp).forEach(function (k) { if (pp[k]) parts.push(portName(k) + ":" + pp[k]); });
      $("#connSub").textContent = parts.length ? parts.join(" · ") : "no active tunnels";
    }
    if ($("#upVal")) $("#upVal").textContent = s.uptime || "—";
    if ($("#rxNow")) {
      $("#rxNow").textContent = "↓ " + UG.speed(n.rx_speed || 0);
      $("#txNow").textContent = "↑ " + UG.speed(n.tx_speed || 0);
    }
    if ($("#rxT")) {
      $("#rxT").textContent = UG.bytes(n.rx_total || 0);
      $("#txT").textContent = UG.bytes(n.tx_total || 0);
      $("#pkRx").textContent = UG.speed(n.peak_rx || 0);
      $("#pkTx").textContent = UG.speed(n.peak_tx || 0);
      $("#loadV").textContent = (s.load || []).map(function (x) { return x.toFixed(2); }).join("  ");
    }
    var g = $("#netG");
    if (g) UG.sparkline(g, [
      { data: S.rx, color: "#00ffc8" }, { data: S.tx, color: "#8b5cf6" }
    ]);
    var sg = $("#scoreG");
    if (sg) {
      UG.gauge(sg, s.score || 0, UG.scoreColor(s.score || 0));
      var v = s.score || 0;
      $("#scoreV").textContent = v >= 85 ? "EXCELLENT" : v >= 70 ? "GOOD" : v >= 50 ? "FAIR" : "DEGRADED";
      $("#scoreV").style.color = UG.scoreColor(v);
      $("#scoreT").innerHTML = "CPU, memory, load and session pressure combined " +
        "into one gaming-latency indicator.<br>Higher is smoother.";
    }
  }

  function portName(p) {
    return ({ "7001": "vless", "7002": "vmess", "7003": "trojan",
      "7004": "xhttp", "7005": "hu" })[p] || p;
  }

  // ── events ─────────────────────────────────────────────────────────
  function loadEvents() {
    var box = $("#evBox"); if (!box) return;
    api("/api/events?limit=40").then(function (evs) {
      if (!evs.length) { box.innerHTML = '<div class="empty">—</div>'; return; }
      box.innerHTML = evs.map(function (e) {
        var c = e.level === "error" ? "var(--red)" : e.level === "warn" ? "var(--amber)" : "var(--muted)";
        return '<div class="kv"><b style="color:' + c + '">' + esc(e.message) + '</b>' +
          '<span>' + UG.ago(e.ts) + '</span></div>';
      }).join("");
    }).catch(function () { });
  }

  // ── users ──────────────────────────────────────────────────────────
  function viewUsers() {
    var rows = S.users.map(function (u) {
      var r = u.rank || {}, q = u.quota_pct;
      var st = !u.enabled ? '<span class="badge b-off">' + t("disabled") + '</span>'
        : u.expired ? '<span class="badge b-off">' + t("expired") + '</span>'
          : '<span class="badge b-on">' + t("enabled") + '</span>';
      return '<tr>' +
        '<td><b>' + esc(u.username) + '</b>' + (u.note ? '<div style="font-size:10.5px;color:var(--muted)">' + esc(u.note) + '</div>' : '') + '</td>' +
        '<td><span class="rank" style="color:' + esc(r.color || "#888") + '">' + esc(r.icon || "") + ' ' + esc(r.name || "") + '</span>' +
          '<div class="track" style="margin-top:5px;height:3px"><div class="fill f-xp" style="width:' + (r.progress || 0) + '%"></div></div></td>' +
        '<td class="mono">' + UG.bytes(u.used_total || 0) +
          (q != null ? '<div style="font-size:10px;color:var(--muted)">' + q + '% of ' + UG.bytes(u.quota_bytes) + '</div>' : '') + '</td>' +
        '<td class="mono">' + (u.days_left != null ? u.days_left + " " + t("days") : t("never")) + '</td>' +
        '<td class="mono">' + (u.last_seen ? UG.ago(u.last_seen) : "—") + '</td>' +
        '<td>' + st + (u.boost && u.boost.active
          ? ' <span class="badge" style="background:rgba(255,211,42,.14);color:var(--yellow);border:1px solid rgba(255,211,42,.3)">🔥</span>'
          : '') + '</td>' +
        '<td style="text-align:right;white-space:nowrap">' +
          '<button class="btn sm" data-act="cfg" data-id="' + u.id + '">' + t("configs") + '</button> ' +
          '<button class="btn sm violet" data-act="wk" data-id="' + u.id + '">📊</button> ' +
          '<button class="btn sm dim" data-act="edit" data-id="' + u.id + '">' + t("edit") + '</button> ' +
          '<button class="btn sm danger" data-act="del" data-id="' + u.id + '">✕</button>' +
        '</td></tr>';
    }).join("");

    return '<div class="card"><div class="title">' + t("users") +
      ' <span style="color:var(--neon)">' + S.users.length + '</span>' +
      '<div class="grow"></div>' +
      '<button class="btn sm dim" id="expJ">JSON</button>' +
      '<button class="btn sm dim" id="expC">CSV</button>' +
      '<button class="btn sm" id="addU">+ ' + t("addplayer") + '</button></div>' +
      (S.users.length ? '<div class="scroll"><table class="tbl"><thead><tr>' +
        '<th>' + t("username") + '</th><th>' + t("rank") + '</th><th>' + t("used") + '</th>' +
        '<th>' + t("expires") + '</th><th>Seen</th><th>' + t("status") + '</th><th></th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>'
        : '<div class="empty"><span class="em">🎮</span>' + t("noplayers") + '</div>') +
      '</div>';
  }

  // ── analytics ──────────────────────────────────────────────────────
  function viewAnalytics() {
    var wins = ["1h", "6h", "24h", "7d", "30d"];
    return '<div class="card"><div class="title">' + t("history") +
      '<div class="grow"></div>' +
      wins.map(function (w) {
        return '<button class="tab' + (S.window === w ? ' on' : '') + '" data-win="' + w + '">' + w + '</button>';
      }).join("") + '</div>' +
      '<canvas class="graph" id="histG" style="height:190px"></canvas>' +
      '<div style="display:flex;gap:16px;margin-top:10px;font-size:11px;color:var(--muted)">' +
      '<span style="color:#00ffc8">— ' + t("download") + '</span>' +
      '<span style="color:#8b5cf6">— ' + t("upload") + '</span>' +
      '<span style="color:#ffa502">— CPU</span></div></div>' +

      '<div class="card"><div class="title">' + t("heatmap") + ' (7d)</div>' +
      '<div class="scroll"><div class="heat" id="heat"></div></div></div>' +

      '<div class="card"><div class="title">' + t("topusers") + '</div>' +
      '<div class="scroll"><table class="tbl" id="lbTbl"><thead><tr>' +
      '<th>#</th><th>' + t("username") + '</th><th>' + t("rank") + '</th>' +
      '<th>' + t("used") + '</th><th>XP</th></tr></thead><tbody>' +
      S.users.slice().sort(function (a, b) { return (b.used_total || 0) - (a.used_total || 0); })
        .map(function (u, i) {
          var r = u.rank || {};
          return '<tr><td class="mono">' + (i + 1) + '</td><td><b>' + esc(u.username) + '</b></td>' +
            '<td><span class="rank" style="color:' + esc(r.color || "#888") + '">' +
            esc(r.icon || "") + ' ' + esc(r.name || "") + '</span></td>' +
            '<td class="mono">' + UG.bytes(u.used_total || 0) + '</td>' +
            '<td class="mono">' + UG.num(u.xp) + '</td></tr>';
        }).join("") + '</tbody></table></div></div>';
  }

  function loadHistory() {
    api("/api/history?window=" + S.window).then(function (h) {
      S.hist = h; paintHistory();
    }).catch(function () { });
    api("/api/heatmap?days=7").then(function (h) {
      S.heat = h; paintHeatmap();
    }).catch(function () { });
  }

  function paintHistory() {
    var cv = $("#histG"); if (!cv || !S.hist) return;
    if (!S.hist.length) { UG.sparkline(cv, [{ data: [0, 0], color: "#333" }]); return; }
    UG.sparkline(cv, [
      { data: S.hist.map(function (r) { return r.rx; }), color: "#00ffc8" },
      { data: S.hist.map(function (r) { return r.tx; }), color: "#8b5cf6" },
      { data: S.hist.map(function (r) { return r.cpu * 1000; }), color: "#ffa502" }
    ]);
  }

  function paintHeatmap() {
    var box = $("#heat"); if (!box) return;
    var data = S.heat || [];
    var grid = {}, max = 1;
    data.forEach(function (d) {
      grid[d.dow + "-" + d.hour] = (grid[d.dow + "-" + d.hour] || 0) + d.bytes;
      max = Math.max(max, grid[d.dow + "-" + d.hour]);
    });
    var days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    var html = '<div></div>';
    for (var h = 0; h < 24; h++) html += '<div class="hh">' + (h % 3 === 0 ? h : "") + '</div>';
    for (var d = 0; d < 7; d++) {
      html += '<div class="hl">' + days[d] + '</div>';
      for (var hh = 0; hh < 24; hh++) {
        var v = grid[d + "-" + hh] || 0, k = v / max;
        var bg = v ? "rgba(0,255,200," + (0.1 + k * 0.85).toFixed(3) + ")" : "rgba(255,255,255,.04)";
        html += '<div class="hc" style="background:' + bg + '" title="' + days[d] + " " + hh + ":00 — " + UG.bytes(v) + '"></div>';
      }
    }
    box.innerHTML = html;
  }

  // ── latency race ───────────────────────────────────────────────────
  // ── Country exits ────────────────────────────────────────────────────
  // Rendered from boot.locations, which the server refreshes as each Tor
  // instance bootstraps and verifies. States are: pending, starting,
  // verifying, ready, failed, restarting, error.
  function locBadge(l) {
    // Reuses the existing .pill modifiers (.warn / .off) rather than
    // inventing new ones, so the badge inherits the panel's theming.
    var map = {
      ready:      ["",     "READY"],
      verifying:  ["warn", "VERIFYING"],
      starting:   ["warn", "STARTING"],
      restarting: ["warn", "RESTARTING"],
      pending:    ["warn", "QUEUED"],
      failed:     ["off",  "FAILED"],
      error:      ["off",  "ERROR"],
      idle:       ["off",  "OFF"]
    };
    var m = map[l.state] || ["warn", String(l.state || "?").toUpperCase()];
    return '<span class="pill ' + m[0] + '">' + m[1] + "</span>";
  }

  function viewLocations() {
    var L = S.locations || { locations: [], history: {}, max: 10,
                             per_location_ram_mb: 40, tor_available: true };
    var list = L.locations || [];
    var q = (S.locSearch || "").toLowerCase();
    if (q) {
      list = list.filter(function (l) {
        // Search matches the English name, the Persian name AND the code,
        // so a فارسی query like «آلمان» finds Germany.
        return (l.label + " " + (l.label_fa || "") + " " + l.code)
          .toLowerCase().indexOf(q) >= 0;
      });
    }
    // Enabled countries first, then alphabetical — the active ones are
    // the ones that matter most, and the flag right before each name
    // makes scanning fast in either order.
    list = list.slice().sort(function (a, b) {
      if (!!a.enabled !== !!b.enabled) return a.enabled ? -1 : 1;
      return a.code < b.code ? -1 : 1;
    });
    var enabledCount = L.enabled_count || 0;
    var rd = L.relay_data || { source: "bundled", updated: null };
    var totalCount = (L.locations || []).length;

    return '<div class="card"><div class="title">🌍 ' + t("locations") +
      '<div class="grow"></div>' +
      '<span class="badge ' + (enabledCount ? "b-on" : "b-off") + '">' +
      enabledCount + "/" + (L.max || 10) + "</span></div>" +
      '<input class="lsearch" id="locSearch" placeholder="' + esc(t("search")) +
      '" value="' + esc(S.locSearch || "") + '">' +
      '<p style="font-size:12.5px;color:var(--muted);line-height:1.7;margin-bottom:14px">' +
      "<b>" + totalCount + "</b> " + esc(t("exitcount")) +
      " · " +
      (rd.source === "live"
        ? '<span style="color:var(--green)">● ' + esc(t("relaylive")) +
          " " + esc(rd.updated ? UG.ago(rd.updated) : "—") + "</span>"
        : '<span style="color:var(--amber)">◐ ' + esc(t("relaybundled")) +
          "</span>") +
      "<br>" +
      (L.tor_available === false
        ? '<span style="color:var(--red)">⚠️ ' + esc(t("torunavail")) + "</span><br>"
        : "") +
      esc(t("ramnote")) + " " + esc(t("maxnote")) + " " + (L.max || 10) +
      ".<br>" +
      '<span style="color:var(--amber)">⚠️ ' + esc(t("exitnote")) + "</span></p>" +
      '<div class="lgrid">' +
      list.map(function (l) {
        return locCard(l, (L.history || {})[l.code] || []);
      }).join("") +
      "</div></div>";
  }

  function locCard(l, hist) {
    var on = !!l.enabled;
    // Show the Persian name when the UI is فارسی; keep English otherwise.
    var fa = UG.lang() === "fa";
    var nm = fa ? (l.label_fa || l.label) : (l.label || l.code);
    return '<div class="lcard' + (on ? "" : " off") + '">' +
      '<div class="lhead">' +
      '<span class="lflag">' + esc(l.flag || "🌍") + "</span>" +
      '<b dir="' + (fa ? "rtl" : "ltr") + '">' + esc(nm) + "</b>" +
      // How many running exit relays this country has right now.
      (l.relays ? '<span class="lrel" title="Running Tor exit relays">' +
        l.relays + '</span>' : "") +
      // Scarce-exit countries fail often and legitimately. Marking them
      // up front stops a FAILED card reading as a panel bug.
      (l.fragile ? '<span class="lfrag" title="This country has very ' +
        'few Tor exit relays, so it may not come up">scarce</span>' : "") +
      (l.pinned ? '<span class="lpin" title="' + esc(t("pinwarn")) + '">📌 ' +
        esc(t("pinned")) + "</span>" : "") +
      '<div class="grow"></div>' + locBadge(l) +
      "</div>" +
      '<div class="lrow"><span>' + esc(t("exitip")) + "</span><code>" +
      esc((l.verified && l.exit_ip) || "—") + "</code></div>" +
      (l.reason ? '<div class="lnote">' + esc(l.reason) + "</div>" : "") +
      // The five most stable exits this country has served, with a pin
      // button per row. Only meaningful while the location is enabled.
      (on && (hist.length || l.pinned)
        ? '<div class="lhist"><div class="lh-title">🎯 ' + esc(t("bestexits")) +
          "</div>" +
          hist.map(function (h) { return histRow(l, h); }).join("") +
          // A freshly pinned exit may not be in the top-5 yet — it must
          // still be unpinnable, or the location could get stuck.
          (l.pinned && !hist.some(function (h) { return h.ip === l.pinned; })
            ? histRow(l, { ip: l.pinned, pct: 0, count: 0 })
            : "") +
          '<div class="lh-note">' + esc(t("pinhint")) + "</div></div>"
        : "") +
      '<button class="btn sm block' + (on ? " dim" : "") + '" data-loc="' +
      esc(l.code) + '" data-locact="' + (on ? "stop" : "start") + '">' +
      (on ? "⏻ " + esc(t("deactivate")) : "▶ " + esc(t("activate"))) +
      "</button></div>";
  }

  function histRow(l, h) {
    var pinned = h.ip === l.pinned;
    return '<div class="lh-row">' +
      "<code>" + esc(h.ip) + "</code>" +
      '<span class="lh-pct">' + h.pct + "%</span>" +
      '<span class="lh-cnt">' + h.count + " " + esc(t("sessions")) +
      "</span>" +
      (pinned
        ? '<button class="btn sm dim" data-locpin="' + esc(l.code) +
          '" data-ip="">' + esc(t("unpin")) + "</button>"
        : '<button class="btn sm" data-locpin="' + esc(l.code) +
          '" data-ip="' + esc(h.ip) + '">📌 ' + esc(t("pin")) + "</button>") +
      "</div>";
  }

  function loadLocations() {
    api("/api/locations").then(function (d) {
      S.locations = d;
      if (S.page === "locations") render();
    }).catch(function () { });
    // Countries take minutes to verify; keep the page fresh while open.
    clearTimeout(S.locTimer);
    S.locTimer = setTimeout(function () {
      if (S.page === "locations") loadLocations();
    }, 20000);
  }

  function locAction(code, act, body) {
    api("/api/locations/" + code + "/" + act,
        { method: "POST", body: body || {} })
      .then(function (d) {
        if (d && d.ok === false) throw new Error(d.error || "failed");
        UG.toast("✅ " + code.toUpperCase() + " — " + act, "ok");
        loadLocations();
      })
      .catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
  }

  function viewRace() {
    var b = S.boot || {};
    var routes = raceRoutes();
    return '<div class="card"><div class="title">🏁 ' + t("race") +
      '<div class="grow"></div><button class="btn" id="raceBtn">' + t("startrace") + '</button></div>' +
      '<p style="font-size:12.5px;color:var(--muted);margin-bottom:16px">' +
      'Each route is probed 8 times. Median RTT, jitter and loss decide the winner — ' +
      'then the fastest config is copied to your clipboard automatically.</p>' +
      '<div id="lanes">' + routes.map(function (r, i) {
        return '<div class="lane" id="lane' + i + '">' +
          '<div class="top"><span>' + r.icon + '</span><b>' + esc(r.name) + '</b>' +
          '<span class="ms" id="ms' + i + '" style="color:var(--muted)">—</span></div>' +
          '<div class="rt"><div class="rf" id="rf' + i + '" style="width:0%;background:' + r.color + ';color:' + r.color + '"></div></div>' +
          '<div style="font-size:10.5px;color:var(--muted);margin-top:4px" id="dt' + i + '">' + esc(r.desc) + '</div>' +
          '</div>';
      }).join("") + '</div>' +
      '<div id="raceResult"></div></div>' +

      // The tunnel itself, measured as a WebSocket echo: this is the RTT a
      // real game session sees (TLS + Cloudflare + nginx + echo), not a
      // short-lived HTTP request.
      '<div class="card" style="margin-top:14px"><div class="title">🔌 ' +
      t("wsrace") + '<div class="grow"></div>' +
      '<button class="btn" id="wsRaceBtn">' + t("wsstart") + '</button></div>' +
      '<p style="font-size:12.5px;color:var(--muted);margin-bottom:16px">' +
      t("wsdesc") + '</p>' +
      '<div id="wsRaceResult"><div class="empty" style="padding:18px">—</div></div></div>';
  }

  function runWsRace() {
    var btn = $("#wsRaceBtn");
    btn.disabled = true; btn.innerHTML = '<span class="sp"></span>';
    var box = $("#wsRaceResult");
    box.innerHTML = '<div class="empty" style="padding:18px"><span class="sp"></span></div>';
    UG.wsProbe((location.protocol === "https:" ? "wss://" : "ws://") +
               location.host + "/__ws", 8)
      .then(function (r) {
        if (r.median == null) {
          box.innerHTML = '<div class="kv"><b>Result</b><span style="color:var(--red)">unreachable</span></div>';
        } else {
          var col = UG.pingColor(r.median);
          box.innerHTML =
            '<div class="kv"><b>Median RTT</b><span style="color:' + col + '">' +
            r.median + ' ms</span></div>' +
            '<div class="kv"><b>Jitter</b><span>' + r.jitter + ' ms</span></div>' +
            '<div class="kv"><b>Min / Max</b><span>' + r.min + ' / ' + r.max + ' ms</span></div>' +
            '<div class="kv"><b>Loss</b><span>' + r.loss + '%</span></div>' +
            '<div class="sub" style="margin-top:8px;color:' + col + '">' +
            UG.pingVerdict(r.median) + '</div>';
        }
        btn.disabled = false; btn.textContent = t("wsstart");
      });
  }

  function raceRoutes() {
    var b = S.boot || {}, host = b.host || location.hostname;
    var rs = [
      { name: "Direct — Railway edge", url: "/__ping", icon: "🚀", color: "#00ffc8",
        desc: "Straight to " + host },
      { name: "Direct — API round-trip", url: "/api/probe", icon: "⚙️", color: "#00d4ff",
        desc: "Includes control-plane processing" }
    ];
    if (b.cf_host) rs.push({
      name: "Cloudflare Worker", url: "https://" + b.cf_host + "/ping", icon: "☁️",
      color: "#ffa502", desc: "Via " + b.cf_host
    });
    return rs;
  }

  function runRace() {
    if (S.raceRunning) return;
    S.raceRunning = true;
    var btn = $("#raceBtn");
    btn.disabled = true; btn.textContent = t("racing");
    $("#raceResult").innerHTML = "";
    var routes = raceRoutes(), N = 8;

    Promise.all(routes.map(function (r, i) {
      return probe(r, N, i);
    })).then(function (res) {
      var valid = res.filter(function (r) { return r.median != null; });
      var best = valid.sort(function (a, b) { return a.median - b.median; })[0];
      var worst = Math.max.apply(null, valid.map(function (r) { return r.median; }).concat([1]));

      res.forEach(function (r, i) {
        var lane = $("#lane" + i), rf = $("#rf" + i), ms = $("#ms" + i), dt = $("#dt" + i);
        if (r.median == null) {
          ms.textContent = "unreachable"; ms.style.color = "var(--red)";
          rf.style.width = "100%"; rf.style.background = "rgba(255,71,87,.25)";
          dt.textContent = "no response";
          return;
        }
        var pct = Math.max(12, 100 - (r.median / worst) * 78);
        rf.style.width = pct + "%";
        rf.textContent = r.median + "ms";
        ms.textContent = r.median + " ms";
        ms.style.color = routes[i].color;
        dt.textContent = "jitter " + r.jitter + "ms · loss " + r.loss + "% · min " +
          r.min + "ms · max " + r.max + "ms";
        if (best && r.name === best.name) lane.classList.add("win");
        else lane.classList.remove("win");
      });

      if (best) {
        $("#raceResult").innerHTML =
          '<div class="cfg star" style="margin-top:16px"><span class="badge b-xhttp">🏆 ' + t("winner") + '</span>' +
          '<div class="info"><div class="nm">' + esc(best.name) + '</div>' +
          '<div class="pt">' + best.median + 'ms median · ' + best.jitter + 'ms jitter · ' + best.loss + '% loss</div></div></div>';
        UG.toast("🏆 " + esc(best.name) + " — " + best.median + "ms", "ok");
      }
      btn.disabled = false; btn.textContent = t("startrace");
      S.raceRunning = false;
    });
  }

  function probe(route, n, idx) {
    var samples = [], fails = 0;
    var chain = Promise.resolve();
    for (var i = 0; i < n; i++) {
      (function (k) {
        chain = chain.then(function () {
          return new Promise(function (resolve) {
            var t0 = performance.now(), done = false;
            var to = setTimeout(function () {
              if (!done) { done = true; fails++; resolve(); }
            }, 3000);
            fetch(route.url + (route.url.indexOf("?") > 0 ? "&" : "?") + "_=" + Date.now() + "-" + k,
              { cache: "no-store", mode: route.url.charAt(0) === "/" ? "same-origin" : "cors" })
              .then(function (r) { return r.text(); })
              .then(function () {
                if (done) return; done = true; clearTimeout(to);
                samples.push(performance.now() - t0);
                var rf = $("#rf" + idx);
                if (rf) rf.style.width = Math.round((k + 1) / n * 60) + "%";
                resolve();
              })
              .catch(function () { if (!done) { done = true; clearTimeout(to); fails++; resolve(); } });
          });
        }).then(function () { return new Promise(function (r) { setTimeout(r, 60); }); });
      })(i);
    }
    return chain.then(function () {
      if (!samples.length) return { name: route.name, median: null };
      samples.sort(function (a, b) { return a - b; });
      var mid = samples[Math.floor(samples.length / 2)];
      var avg = samples.reduce(function (a, b) { return a + b; }, 0) / samples.length;
      var jit = Math.sqrt(samples.reduce(function (a, b) { return a + Math.pow(b - avg, 2); }, 0) / samples.length);
      return {
        name: route.name, median: Math.round(mid), jitter: Math.round(jit),
        min: Math.round(samples[0]), max: Math.round(samples[samples.length - 1]),
        loss: Math.round(fails / n * 100)
      };
    });
  }



  // ── per-user chart + boost helpers (ideas #4, #7) ──────────────────
  function loadUserChart(id, win) {
    api("/api/users/" + id + "/history?window=" + win).then(function (r) {
      var cv = $("#uG");
      if (!cv) return;
      var s = r.series || [];
      if (!s.length) {
        UG.sparkline(cv, [{ data: [0, 0], color: "#2a2a35" }]);
        var sum0 = $("#uSum");
        if (sum0) sum0.innerHTML = '<div class="empty">' + t("noData") + '</div>';
        return;
      }
      UG.sparkline(cv, [
        { data: s.map(function (x) { return x.down; }), color: "#00ffc8" },
        { data: s.map(function (x) { return x.up; }), color: "#8b5cf6" }
      ]);
      var down = s.reduce(function (a, b) { return a + b.down; }, 0);
      var up = s.reduce(function (a, b) { return a + b.up; }, 0);
      var peak = s.reduce(function (a, b) {
        return b.total > (a ? a.total : -1) ? b : a;
      }, null);
      var sum = $("#uSum");
      if (sum) sum.innerHTML =
        '<div class="kv"><b>↓ Downloaded</b><span style="color:var(--neon)">' +
        UG.bytes(down) + '</span></div>' +
        '<div class="kv"><b>↑ Uploaded</b><span style="color:var(--neon2)">' +
        UG.bytes(up) + '</span></div>' +
        '<div class="kv"><b>Total</b><span>' + UG.bytes(down + up) + '</span></div>' +
        (peak ? '<div class="kv"><b>Busiest bucket</b><span>' +
          UG.bytes(peak.total) + ' @ ' +
          new Date(peak.t * 1000).toLocaleString() + '</span></div>' : '') +
        '<button class="btn block violet" id="wkBtn" style="margin-top:12px">' +
        '📊 ' + t("weekly") + '</button>';
      var wk = $("#wkBtn");
      if (wk) wk.addEventListener("click", function () { weeklyModal(id); });
    }).catch(function () { });
  }

  function boostRow(u) {
    var b = u.boost || { active: false };
    if (b.active) {
      return '<div class="boostbar" id="boostBar">' +
        '<span class="fire">🔥</span>' +
        '<div class="info"><b>' + t("boostactive") + '</b>' +
        '<span>' + t("boostdesc") + '</span></div>' +
        '<span class="cd" id="boostCd">' + UG.mmss(b.remaining) + '</span>' +
        '<button class="btn sm dim" id="boostOff">Stop</button></div>';
    }
    return '<div class="boostbar" id="boostBar" style="opacity:.75">' +
      '<span style="font-size:22px">⚡</span>' +
      '<div class="info"><b style="color:var(--muted)">' + t("boost") + '</b>' +
      '<span>' + t("boostdesc") + '</span></div>' +
      '<button class="btn" id="boostOn">' + t("boostoff") + '</button></div>';
  }

  var boostTimer = null;
  function wireBoost(id, u) {
    if (boostTimer) { clearInterval(boostTimer); boostTimer = null; }
    var on = $("#boostOn"), off = $("#boostOff"), cd = $("#boostCd");

    if (on) on.addEventListener("click", function () {
      on.disabled = true; on.innerHTML = '<span class="sp"></span>';
      api("/api/users/" + id + "/boost", { method: "POST", body: { minutes: 30 } })
        .then(function () {
          UG.toast("🔥 Boost activated for 30 minutes", "xp");
          configModal(id); refreshUsers();
        }).catch(function (e) {
          UG.toast("❌ " + esc(e.message), "err");
          on.disabled = false; on.textContent = t("boostoff");
        });
    });

    if (off) off.addEventListener("click", function () {
      off.disabled = true;
      api("/api/users/" + id + "/unboost", { method: "POST", body: {} })
        .then(function () {
          UG.toast("Boost stopped", "ok"); configModal(id); refreshUsers();
        }).catch(function (e) { UG.toast("❌ " + esc(e.message), "err"); });
    });

    if (cd && u.boost && u.boost.active) {
      var left = u.boost.remaining;
      boostTimer = setInterval(function () {
        left--;
        var el = $("#boostCd");
        if (!el) { clearInterval(boostTimer); boostTimer = null; return; }
        if (left <= 0) {
          clearInterval(boostTimer); boostTimer = null;
          UG.toast("Boost finished", "ok"); configModal(id); refreshUsers();
          return;
        }
        el.textContent = UG.mmss(left);
      }, 1000);
    }
  }

  // ── game server ping (idea #5) ─────────────────────────────────────
  function viewGames() {
    var games = (S.boot && S.boot.games) || [];
    return '<div class="card"><div class="title">🎮 ' + t("gameping") +
      '<div class="grow"></div>' +
      '<button class="btn" id="pingAll">' + t("testping") + '</button></div>' +
      '<p style="font-size:12.5px;color:var(--muted);margin-bottom:15px">' +
      'Measures round-trip time from <b>your browser</b> to each publisher\'s ' +
      'edge. Run it with the VPN on and off to see what the tunnel costs you.</p>' +
      '<div class="gamegrid">' + games.map(function (g) {
        return '<div class="gcard" data-game="' + esc(g.id) + '">' +
          '<div class="hd"><span class="em">' + esc(g.icon) + '</span>' +
          '<b>' + esc(g.name) + '</b>' +
          '<button class="btn sm dim" data-pg="' + esc(g.id) + '">▶</button></div>' +
          g.regions.map(function (r, i) {
            return '<div class="rg"><span class="fl">' + esc(r.flag) + '</span>' +
              '<span class="nm">' + esc(r.label) + '</span>' +
              '<span class="pingdot" id="pd-' + esc(g.id) + '-' + i + '" ' +
              'style="background:rgba(255,255,255,.12)"></span>' +
              '<span class="ms" id="pm-' + esc(g.id) + '-' + i + '" ' +
              'style="color:var(--muted)">—</span></div>';
          }).join("") + '</div>';
      }).join("") + '</div></div>';
  }

  function pingGame(gid) {
    var g = ((S.boot && S.boot.games) || []).filter(function (x) {
      return x.id === gid;
    })[0];
    if (!g) return Promise.resolve();
    return Promise.all(g.regions.map(function (r, i) {
      var dot = $("#pd-" + gid + "-" + i), lbl = $("#pm-" + gid + "-" + i);
      if (lbl) { lbl.textContent = "..."; lbl.style.color = "var(--muted)"; }
      return UG.probe(r.url, 5).then(function (res) {
        if (!lbl || !dot) return;
        if (res.median == null) {
          lbl.textContent = "n/a"; lbl.style.color = "var(--red)";
          dot.style.background = "var(--red)";
        } else {
          var c = UG.pingColor(res.median);
          lbl.textContent = res.median + "ms";
          lbl.style.color = c; dot.style.background = c;
          dot.title = "jitter " + res.jitter + "ms · loss " + res.loss + "%";
        }
      });
    }));
  }

  function pingAllGames() {
    var btn = $("#pingAll");
    if (!btn) return;
    btn.disabled = true; btn.innerHTML = '<span class="sp"></span>';
    var games = (S.boot && S.boot.games) || [];
    var chain = Promise.resolve();
    games.forEach(function (g) {
      chain = chain.then(function () { return pingGame(g.id); });
    });
    chain.then(function () {
      btn.disabled = false; btn.textContent = t("testping");
      UG.toast("🎮 Ping test complete", "ok");
    });
  }

  // ── trials (idea #19) ──────────────────────────────────────────────
  function viewTrials() {
    return '<div class="card"><div class="title">🎁 ' + t("trials") +
      '<div class="grow"></div>' +
      '<button class="btn" id="newTrial">+ ' + t("newtrial") + '</button></div>' +
      '<p style="font-size:12.5px;color:var(--muted);margin-bottom:15px">' +
      'Share a trial link and anyone who opens it gets a temporary account ' +
      'instantly — no admin work. One claim per IP per day.</p>' +
      '<div id="trialList"><div class="empty"><span class="sp"></span></div></div>' +
      '</div>';
  }

  function loadTrials() {
    api("/api/trials").then(function (list) {
      var box = $("#trialList");
      if (!box) return;
      if (!list.length) {
        box.innerHTML = '<div class="empty"><span class="em">🎁</span>' +
          'No trial links yet</div>';
        return;
      }
      box.innerHTML = list.map(function (tr) {
        var left = Math.max(0, tr.max_claims - tr.claims);
        return '<div class="trialcard">' +
          '<span class="badge ' + (tr.enabled ? 'b-on' : 'b-off') + '">' +
          (tr.enabled ? 'LIVE' : 'OFF') + '</span>' +
          '<div class="info"><b>' + tr.quota_gb + ' GB · ' + tr.hours + 'h</b>' +
          '<span>' + esc(tr.url) + '</span></div>' +
          '<div style="font-size:11px;color:var(--muted);text-align:right">' +
          tr.claims + '/' + tr.max_claims + ' used<br>' +
          left + ' left · ' + tr.claimed_today + ' today</div>' +
          '<button class="btn sm" data-tcp="' + esc(tr.url) + '">' + t("copy") + '</button>' +
          '<button class="btn sm dim" data-tqr="' + esc(tr.url) + '">' + t("qr") + '</button>' +
          '<button class="btn sm dim" data-tt="' + tr.id + '" data-en="' +
          (tr.enabled ? '0' : '1') + '">' + (tr.enabled ? 'Pause' : 'Resume') + '</button>' +
          '<button class="btn sm danger" data-td="' + tr.id + '">✕</button>' +
          '</div>';
      }).join("") + '<div id="trialQr" style="text-align:center;margin-top:14px"></div>';
    }).catch(function (e) { UG.toast(esc(e.message), "err"); });
  }

  function trialModal() {
    modal('<h3>🎁 ' + t("newtrial") + '</h3>' +
      '<div class="row2">' +
      '<div class="field"><label>' + t("quota") + ' (GB)</label>' +
      '<input id="tQ" type="number" min="0.1" step="0.5" value="1"></div>' +
      '<div class="field"><label>Duration (hours)</label>' +
      '<input id="tH" type="number" min="1" max="720" value="24"></div></div>' +
      '<div class="row2">' +
      '<div class="field"><label>Total ' + t("claims") + '</label>' +
      '<input id="tM" type="number" min="1" max="1000" value="10"></div>' +
      '<div class="field"><label>' + t("perday") + '</label>' +
      '<input id="tD" type="number" min="1" max="100" value="5"></div></div>' +
      '<div class="acts"><button class="btn dim" onclick="ugClose()">' + t("cancel") + '</button>' +
      '<button class="btn" id="tSave">' + t("save") + '</button></div>');
    $("#tSave").addEventListener("click", function () {
      api("/api/trials", { method: "POST", body: {
        quota_gb: parseFloat($("#tQ").value) || 1,
        hours: parseInt($("#tH").value) || 24,
        max_claims: parseInt($("#tM").value) || 10,
        per_day: parseInt($("#tD").value) || 5
      }}).then(function () {
        close(); UG.toast("🎁 Trial link created", "ok"); loadTrials();
      }).catch(function (e) { UG.toast("❌ " + esc(e.message), "err"); });
    });
  }

  // ── weekly report (idea #14) ───────────────────────────────────────
  function weeklyModal(id) {
    modal('<div class="empty"><span class="sp"></span></div>');
    api("/api/users/" + id + "/weekly").then(function (w) {
      var tr = w.traffic || {};
      var days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
      var byDow = {};
      (tr.daily || []).forEach(function (d) { byDow[d.dow] = d.bytes; });
      var max = Math.max.apply(null, days.map(function (_, i) {
        return byDow[i] || 0;
      }).concat([1]));

      var chg = tr.change_pct;
      var chgTxt = chg == null ? "—"
        : (chg > 0 ? "▲ +" : chg < 0 ? "▼ " : "= ") + Math.abs(chg) + "%";
      var chgCol = chg == null ? "var(--muted)"
        : chg > 0 ? "var(--neon)" : chg < 0 ? "var(--amber)" : "var(--muted)";

      $("#modalRoot .modal").innerHTML =
        '<div class="wrap-report">' +
        '<h2>' + esc(w.username) + '</h2>' +
        '<div class="sub">WEEK IN REVIEW · ' + UG.when(tr.from) + ' → ' + UG.when(tr.to) + '</div>' +

        '<div class="bigstat">' +
        '<div><b style="color:var(--neon)">' + UG.bytes(tr.total || 0) + '</b><span>Total</span></div>' +
        '<div><b style="color:var(--neon2)">' + UG.bytes(tr.avg_per_day || 0) + '</b><span>Per day</span></div>' +
        '<div><b style="color:' + chgCol + '">' + chgTxt + '</b><span>vs last week</span></div>' +
        '<div><b style="color:' + esc(w.rank.color) + '">' + esc(w.rank.icon) + '</b><span>' + esc(w.rank.name) + '</span></div>' +
        '</div>' +

        '<div class="daybars">' + days.map(function (_, i) {
          var v = byDow[i] || 0;
          return '<div class="d" title="' + days[i] + ': ' + UG.bytes(v) + '">' +
            '<i style="height:' + Math.max(3, v / max * 100) + '%"></i></div>';
        }).join("") + '</div>' +
        '<div class="daybars lbls">' + days.map(function (d) {
          return '<span>' + d + '</span>';
        }).join("") + '</div>' +

        '<div style="margin-top:18px">' + (w.highlights || []).map(function (h) {
          return '<div class="hilite"><span class="b">▸</span><span>' + esc(h) + '</span></div>';
        }).join("") + '</div>' +

        (w.projection ? '<div class="kv" style="margin-top:14px">' +
          '<b>At this rate, quota lasts</b><span style="color:' +
          (w.projection.days_left < 3 ? 'var(--red)' : 'var(--neon)') + '">' +
          w.projection.days_left + ' days</span></div>' : '') +

        '<div class="kv"><b>Achievements</b><span>' + w.achievements.count +
        ' / ' + w.achievements.total + '</span></div>' +
        '</div>' +
        '<div class="acts"><button class="btn dim" onclick="ugClose()">Close</button></div>';
    }).catch(function (e) {
      $("#modalRoot .modal").innerHTML = '<h3>' + t("error") + '</h3><p>' +
        esc(e.message) + '</p><div class="acts">' +
        '<button class="btn dim" onclick="ugClose()">Close</button></div>';
    });
  }


  // ── console ────────────────────────────────────────────────────────
  function viewConsole() {
    return '<div class="term">' +
      '<div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i>' +
      '<i style="background:#28c840"></i>&nbsp;ULTRA@GAMING — type <b>help</b></div>' +
      '<div class="out" id="tOut"></div>' +
      '<div class="in"><span>❯</span><input id="tIn" autocomplete="off" spellcheck="false" ' +
      'placeholder="help"></div></div>';
  }

  var hist = [], hi = -1;
  function initConsole() {
    var out = $("#tOut"), inp = $("#tIn");
    if (!out) return;
    write(out, "ULTRA GAMING VPN — control console\ntype 'help' for commands\n", "");
    inp.focus();
    inp.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var c = inp.value.trim(); if (!c) return;
        hist.unshift(c); hi = -1; inp.value = "";
        write(out, "❯ " + c, "cmd");
        if (c === "clear") { out.innerHTML = ""; return; }
        api("/api/terminal", { method: "POST", body: { cmd: c } })
          .then(function (r) { write(out, r.out, ""); })
          .catch(function (err) { write(out, err.message, "er"); });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (hi < hist.length - 1) { hi++; inp.value = hist[hi]; }
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        if (hi > 0) { hi--; inp.value = hist[hi]; } else { hi = -1; inp.value = ""; }
      }
    });
  }
  function write(out, text, cls) {
    var d = document.createElement("div");
    if (cls) d.className = cls;
    d.textContent = text;
    out.appendChild(d); out.scrollTop = out.scrollHeight;
  }

  // ── settings ───────────────────────────────────────────────────────
  function viewSettings() {
    var b = S.boot || {}, st = b.settings || {};
    var paths = b.paths || {};
    return '<div class="row2">' +
      '<div class="card"><div class="title">⚡ ' + t("turbo") + '</div>' +
      '<p style="font-size:12.5px;color:var(--muted);margin-bottom:14px">' + t("turbodesc") +
      ' — disables buffering, shortens idle timeouts and drops handshake time. ' +
      'Best for competitive play; slightly higher CPU.</p>' +
      '<button class="btn block ' + (st.turbo_mode ? "" : "dim") + '" id="turboBtn">' +
      (st.turbo_mode ? "⚡ TURBO ON" : "TURBO OFF") + '</button></div>' +

      '<div class="card"><div class="title">🔧 ' + t("xray") + '</div>' +
      '<div class="kv"><b>Status</b><span>' + ((S.stats && S.stats.xray) ? "🟢 " + t("online") : "🔴 " + t("offline")) + '</span></div>' +
      '<div class="kv"><b>Host</b><span>' + esc(b.host || "") + '</span></div>' +
      '<div class="kv"><b>CF Worker</b><span>' + esc(b.cf_host || "not set") + '</span></div>' +
      '<div class="kv"><b>Players</b><span>' + (b.user_count || 0) + ' (' + (b.active_count || 0) + ' active)</span></div>' +
      '<button class="btn block dim" id="reloadBtn" style="margin-top:12px">↻ ' + t("reload") + '</button></div>' +
      '</div>' +

      '<div class="card"><div class="title">🌐 Config hostnames' +
      '<div class="grow"></div>' +
      '<span class="badge ' + ((b.hosts || []).length > 1 ? 'b-on' : 'b-off') +
      '">' + ((b.hosts || []).length) + '</span></div>' +
      '<p style="font-size:12px;color:var(--muted);margin-bottom:12px">' +
      'Every subscription contains one config per protocol per hostname, so a ' +
      'player keeps a working entry if one name stops resolving for them.</p>' +
      (b.hosts || []).map(function (x) {
        return '<div class="kv"><b>' + esc(x.label) + '</b><span>' +
          esc(x.host) + '</span></div>';
      }).join('') +
      ((b.hosts || []).length < 2
        ? '<div class="warn" style="background:rgba(255,165,2,.08);' +
          'border:1px solid rgba(255,165,2,.28);border-radius:10px;' +
          'padding:11px 13px;font-size:12.5px;color:var(--amber);' +
          'margin-top:12px;line-height:1.6">' +
          '⚠️ Only one hostname is active.' +
          (b.railway_domain ? '' :
            '<br>Railway did not provide <code>RAILWAY_PUBLIC_DOMAIN</code> — ' +
            'that variable only exists once the service has a generated ' +
            '<code>*.up.railway.app</code> domain.' +
            '<br><b>Fix:</b> Railway → Settings → Networking → ' +
            '<b>Generate Domain</b>, then redeploy. Or set ' +
            '<code>ALT_HOSTS</code> to the hostname manually.') +
          '</div>'
        : '') +
      '</div>' +

      '<div class="card"><div class="title">🕵️ Transport paths (secret)</div>' +
      '<p style="font-size:12px;color:var(--muted);margin-bottom:12px">' +
      'Anything outside these paths shows the decoy site. Rotate them by changing ' +
      '<code>PATH_SECRET</code> in Railway.</p>' +
      Object.keys(paths).map(function (k) {
        return '<div class="kv"><b>' + esc(k) + '</b><span>' + esc(paths[k]) + '</span></div>';
      }).join("") + '</div>' +

      // Smart fragment (anti-DPI): splits only the TLS ClientHello into
      // pieces, which slips past SNI-based DPI on many ISPs. Applied to
      // every vless link when a mode is set (v2rayNG/NekoBox/v2rayN);
      // Clash and sing-box do not support it.
      '<div class="card"><div class="title">🧩 ' + t("smartfragment") +
      '<div class="grow"></div>' +
      '<span class="badge ' + ((st.smart_fragment || "") ? "b-on" : "b-off") +
      '">' + esc(st.smart_fragment || t("sfoff")) + '</span></div>' +
      '<p style="font-size:12px;color:var(--muted);line-height:1.6;margin-bottom:12px">' +
      t("sfdesc") + '</p>' +
      '<div class="row2" style="gap:8px">' +
      ["", "light", "medium", "aggressive"].map(function (m) {
        return '<button class="btn sm' + ((st.smart_fragment || "") === m
          ? "" : " dim") + '" data-sf="' + m + '">' +
          (m ? esc(m) : t("sfoff")) + '</button>';
      }).join("") + '</div>' +
      '<div id="sfNote" style="margin-top:10px;font-size:11px;color:var(--muted)"></div></div>' +

      // Pinned CDN IPs (Fixed IP): configs that dial a fixed IP while
      // keeping the hostname as SNI.
      '<div class="card"><div class="title">FIXED IP<div class="grow"></div><button class="btn sm dim" id="cfIpsCheck">' +
      t("cfipscheck") + '</button></div>' +
      '<p style="font-size:12px;color:var(--muted);line-height:1.6;margin-bottom:12px">' +
      t("cfipsdesc") + '</p>' +
      '<input class="lsearch" id="cfIps" spellcheck="false" ' +
      'placeholder="104.16.132.229, 104.17.24.14" value="' +
      esc((st.cf_ips || "")) + '">' +
      '<button class="btn block" id="cfIpsSave" style="margin-top:8px">' +
      'Save</button>' +
      '<div id="cfIpsRes" style="margin-top:10px;font-size:11.5px;color:var(--muted)"></div></div>' +

      // REALITY — strongest anti-censorship transport (raw TCP + XTLS Vision)
      (function(){
        var r = (b.reality || {enabled:false});
        var on2 = !!r.enabled;
        return '<div class="card" style="border-color:' + (on2 ? 'rgba(16,185,129,.28)' : 'var(--border)') + '">' +
          '<div class="title">REALITY (VLESS + XTLS Vision) <div class="grow"></div>' +
          '<span class="badge ' + (on2 ? 'b-on' : 'b-off') + '">' + (on2 ? 'ON' : 'OFF') + '</span></div>' +
          '<p style="font-size:12px;color:var(--muted);line-height:1.6;margin-bottom:12px">' +
          'Strongest bypass: REALITY mimics a real site at TLS level. ' +
          'No domain or CDN needed. Requires a dedicated TCP port exposed in Railway (see docs/reality.md).</p>' +
          '<button class="btn block ' + (on2 ? '' : 'dim') + '" id="realityToggle">' + (on2 ? 'Disable REALITY' : 'Enable REALITY') + '</button>' +
          '<div style="margin-top:12px;display:' + (on2 ? 'block' : 'none') + '" id="realityFields">' +
            '<div class="row2"><div class="field"><label>Dest (mimicked site)</label><input id="rDest" value="' + esc(r.dest || 'www.microsoft.com:443') + '" placeholder="www.microsoft.com:443"></div>' +
            '<div class="field"><label>SNI</label><input id="rSni" value="' + esc(r.sni || 'www.microsoft.com') + '" placeholder="www.microsoft.com"></div></div>' +
            '<div class="row2"><div class="field"><label>Fingerprint</label><select id="rFp"><option value="chrome"' + (r.fp==='chrome'?' selected':'') + '>chrome</option><option value="firefox"' + (r.fp==='firefox'?' selected':'') + '>firefox</option><option value="safari"' + (r.fp==='safari'?' selected':'') + '>safari</option><option value="random"' + (r.fp==='random'?' selected':'') + '>random</option></select></div>' +
            '<div class="field"><label>Port (TCP, outside nginx)</label><input id="rPort" type="number" min="1" max="65535" value="' + esc(String(r.port || 8443)) + '"></div></div>' +
            '<div class="field"><label>Public host for link (optional)</label><input id="rHost" value="' + esc(r.host || '') + '" placeholder="auto"></div>' +
            '<div class="kv" style="margin-top:8px"><b>Public key</b><span style="font-size:10px">' + esc(r.pbk || '—') + '</span></div>' +
            '<div class="kv"><b>Short ID</b><span>' + esc(r.sid || '—') + '</span></div>' +
            '<div class="acts"><button class="btn dim" id="rRotate">Rotate keys</button><button class="btn" id="rSave">Save REALITY</button></div>' +
            '<div id="rMsg" style="margin-top:8px;font-size:11px;color:var(--muted)"></div>' +
          '</div></div>';
      })() +

      '<div class="card"><div class="title">THEME</div>' +
      '<div class="themes">' + UG.THEMES.map(function (th) {
        return '<button class="thm' + (UG.theme() === th.id ? ' on' : '') +
          '" data-th="' + th.id + '">' +
          '<span class="sw"><i style="background:' + th.c1 + '"></i>' +
          '<i style="background:' + th.c2 + '"></i></span>' +
          '<b>' + esc(th.label) + '</b></button>';
      }).join("") + '</div>' +
      '<div class="row2" style="margin-top:13px">' +
      '<div class="field"><label>Custom accent</label>' +
      '<input type="color" id="cc1" value="' +
      (localStorage.getItem("ug_c1") || "#00ffc8") + '" style="height:38px;padding:3px"></div>' +
      '<div class="field"><label>Custom secondary</label>' +
      '<input type="color" id="cc2" value="' +
      (localStorage.getItem("ug_c2") || "#8b5cf6") + '" style="height:38px;padding:3px"></div>' +
      '</div><button class="btn" id="applyCustom">Apply custom</button></div>' +

      '<div class="card"><div class="title">🔔 Alert thresholds</div>' +
      '<div class="row2">' +
      '<div class="field"><label>CPU %</label><input type="number" id="alCpu" value="' + (st.alert_cpu || 85) + '" min="10" max="100"></div>' +
      '<div class="field"><label>Quota %</label><input type="number" id="alQ" value="' + (st.alert_quota_pct || 90) + '" min="10" max="100"></div>' +
      '</div><button class="btn" id="saveAl">' + t("save") + '</button></div>';
  }

  // ══ MODALS ══════════════════════════════════════════════════════════
  function modal(html) {
    var root = $("#modalRoot");
    root.innerHTML = '<div class="mask" id="mask"><div class="modal">' + html + '</div></div>';
    $("#mask").addEventListener("click", function (e) { if (e.target.id === "mask") close(); });
    document.addEventListener("keydown", escClose);
  }
  function escClose(e) { if (e.key === "Escape") close(); }
  function close() {
    $("#modalRoot").innerHTML = "";
    document.removeEventListener("keydown", escClose);
  }
  window.ugClose = close;

  // Per-config picker for the user modal.
  //
  // Every row is one real config the panel can hand out, so a user can be
  // given exactly "XHTTP on the direct host" or "the US exit only".
  // Nothing checked means everything, which is the stored default.
  var KIND_ICON = {
    httpupgrade: "\u26a1", xhttp: "\ud83d\udce6", ws: "\ud83d\udd0c",
    trojan: "\ud83d\udee1", vmess: "\ud83d\udd11", location: "\ud83c\udf0d"
  };

  function kindPicker(selected, entries) {
    var sel = selected || [];
    // `entries` may legitimately be an empty array — meaning the server
    // reported no configs — so only fall back when it was not supplied.
    var list = entries != null ? entries : ((S.boot || {}).selectable || []);
    if (!list.length) return "";

    // Group by host so "everything on Railway" is one glance, and so the
    // list stays readable once ten countries exist on two hostnames.
    var groups = {}, order = [];
    list.forEach(function (e) {
      var g = e.via || "Direct";
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(e);
    });

    return '<div class="field"><label>Configs in this subscription</label>' +
      order.map(function (g) {
        return '<div class="kgrp"><div class="ghead">' + esc(g) +
          '<button type="button" class="gall" data-g="' + esc(g) +
          '">all</button>' +
          '<button type="button" class="gnone" data-g="' + esc(g) +
          '">none</button></div>' +
          groups[g].map(function (e) {
            var on = sel.indexOf(e.id) >= 0 || sel.indexOf(e.kind) >= 0 ||
              (e.kind === "location" &&
                sel.indexOf(e.id.split("@")[0]) >= 0);
            return '<label class="kopt' + (on ? " on" : "") +
              '" data-g="' + esc(g) + '">' +
              '<input type="checkbox" class="fK" value="' + esc(e.id) + '"' +
              (on ? " checked" : "") + ">" +
              '<span class="kname">' + (KIND_ICON[e.kind] || "") + " " +
              esc(e.label.replace(/\s*\([^)]*\)\s*$/, "")) + "</span>" +
              '<span class="kdesc">' + esc(e.id) + "</span>" +
              "</label>";
          }).join("") + "</div>";
      }).join("") +
      '<div class="hint">Leave everything unchecked to include all ' +
      "configs. Selections survive a config becoming temporarily " +
      "unavailable.</div></div>";
  }

  // The .on class is applied at render time; without this the highlight
  // never follows the checkbox and the selection looks stuck.
  function bindKindPicker() {
    $$(".fK").forEach(function (c) {
      c.addEventListener("change", function () {
        c.closest(".kopt").classList.toggle("on", c.checked);
      });
    });
    function setGroup(g, on) {
      $$('.kopt[data-g="' + g + '"]').forEach(function (o) {
        var cb = o.querySelector(".fK");
        cb.checked = on;
        o.classList.toggle("on", on);
      });
    }
    $$(".gall").forEach(function (b) {
      b.addEventListener("click", function () { setGroup(b.dataset.g, true); });
    });
    $$(".gnone").forEach(function (b) {
      b.addEventListener("click", function () { setGroup(b.dataset.g, false); });
    });
  }

  function readKinds() {
    var out = [];
    $$(".fK").forEach(function (c) { if (c.checked) out.push(c.value); });
    return out;
  }

  function userModal(u) {
    var isNew = !u;
    u = u || {};
    modal('<h3>' + (isNew ? t("addplayer") : t("edit") + " — " + esc(u.username)) + '</h3>' +
      '<div class="field"><label>' + t("username") + '</label>' +
      '<input id="fU" value="' + esc(u.username || "") + '" placeholder="player-two" maxlength="32">' +
      '<div class="hint">2–32 characters: letters, digits, . _ -</div></div>' +
      '<div class="row2">' +
      '<div class="field"><label>' + t("quota") + ' (GB)</label>' +
      '<input id="fQ" type="number" min="0" step="0.5" value="' +
      (u.quota_bytes ? (u.quota_bytes / 1073741824) : 0) + '"><div class="hint">0 = ' + t("unlimited") + '</div></div>' +
      '<div class="field"><label>' + t("expires") + ' (' + t("days") + ')</label>' +
      '<input id="fD" type="number" min="0" value="' + (u.days_left != null ? u.days_left : 0) + '">' +
      '<div class="hint">0 = ' + t("never") + '</div></div></div>' +
      '<div class="field"><label>Note</label><input id="fN" value="' + esc(u.note || "") + '" maxlength="200"></div>' +
      kindPicker(u.allowed_kinds, (S.boot || {}).selectable) +
      (!isNew ? '<div class="field"><label>' + t("status") + '</label>' +
        '<select id="fE"><option value="1"' + (u.enabled ? " selected" : "") + '>' + t("enabled") + '</option>' +
        '<option value="0"' + (!u.enabled ? " selected" : "") + '>' + t("disabled") + '</option></select></div>' +
        '<div class="field"><label><input type="checkbox" id="fR" style="width:auto;margin-right:7px">' +
        ' Reset traffic counters</label></div>' : '') +
      '<div class="acts">' +
      (!isNew ? '<button class="btn dim" id="mRot">' + t("reset") + '</button>' : '') +
      '<button class="btn dim" onclick="ugClose()">' + t("cancel") + '</button>' +
      '<button class="btn" id="mSave">' + t("save") + '</button></div>');

    bindKindPicker();

    $("#mSave").addEventListener("click", function () {
      var body = {
        username: $("#fU").value.trim(),
        quota_gb: parseFloat($("#fQ").value) || 0,
        days: parseInt($("#fD").value) || 0,
        note: $("#fN").value,
        allowed_kinds: readKinds()
      };
      if (!isNew) {
        body.enabled = $("#fE").value === "1";
        body.reset_traffic = $("#fR").checked;
      }
      var p = isNew ? api("/api/users", { method: "POST", body: body })
        : api("/api/users/" + u.id, { method: "PATCH", body: body });
      p.then(function (nu) {
        close(); UG.toast("✅ " + esc(nu.username) + " saved", "ok");
        refreshUsers();
      }).catch(function (e) { UG.toast("❌ " + esc(e.message), "err"); });
    });

    if (!isNew) $("#mRot").addEventListener("click", function () {
      if (!confirm("Rotate UUID, passwords and subscription token? Old configs stop working.")) return;
      api("/api/users/" + u.id + "/reset", { method: "POST", body: {} })
        .then(function () { close(); UG.toast("🔑 Keys rotated", "ok"); refreshUsers(); })
        .catch(function (e) { UG.toast("❌ " + esc(e.message), "err"); });
    });
  }

  function configModal(id) {
    modal('<h3>' + t("configs") + '</h3><div class="empty"><span class="sp"></span></div>');
    api("/api/users/" + id + "/configs?profile=" + S.profile +
        "&lang=" + UG.lang()).then(function (d) {
      var b = S.boot || {}, profs = b.profiles || [];
      var origin = location.origin;
      var html = '<h3>' + esc(d.user.username) + ' — ' + t("configs") + '</h3>' +

        '<div class="rankbig" style="margin-bottom:16px">' +
        '<span class="em" style="color:' + esc(d.user.rank.color) + '">' + esc(d.user.rank.icon) + '</span>' +
        '<div class="t" style="flex:1"><b style="color:' + esc(d.user.rank.color) + '">' + esc(d.user.rank.name) + '</b>' +
        '<span>' + UG.num(d.user.xp) + ' XP' + (d.user.rank.next ? ' → ' + esc(d.user.rank.next) : ' — MAX') + '</span>' +
        '<div class="track" style="margin-top:6px"><div class="fill f-xp" style="width:' + d.user.rank.progress + '%"></div></div>' +
        '</div></div>' +

        '<div class="field"><label>' + t("profile") + '</label><select id="pfSel">' +
        profs.map(function (p) {
          return '<option value="' + p.id + '"' + (p.id === S.profile ? " selected" : "") + '>' +
            p.icon + " " + esc(p.label) + '</option>';
        }).join("") + '</select>' +
        '<div class="hint" id="pfHint"></div></div>' +

        '<div class="tabs" style="margin-top:14px">' +
        '<button class="tab on" data-ct="links">Links</button>' +
        '<button class="tab" data-ct="sub">' + t("subscription") + '</button>' +
        '<button class="tab" data-ct="act">' + t("myactivity") + '</button>' +
        '<button class="tab" data-ct="ach">' + t("achievements") + '</button></div>' +

        boostRow(d.user) +

        '<div id="ctLinks">' + d.configs.map(function (c, i) {
          return '<div class="cfg' + (c.featured ? " star" : "") + '">' +
            '<span class="badge ' + c.badge + '">' + esc(c.kind.toUpperCase()) + '</span>' +
            '<div class="info"><div class="nm">' + esc(c.label) + '</div>' +
            '<div class="pt">' + esc(c.path) + (c.note ? ' · ' + esc(c.note) : '') + '</div></div>' +
            '<button class="btn sm" data-cp="' + i + '">' + t("copy") + '</button>' +
            '<button class="btn sm dim" data-qr="' + i + '">' + t("qr") + '</button></div>';
        }).join("") + '</div>' +

        '<div id="ctSub" class="hide">' +
        subRow("v2rayN / Base64", origin + d.sub.base64.replace(/^https?:\/\/[^/]+/, "")) +
        subRow("Clash Meta", origin + d.sub.clash.replace(/^https?:\/\/[^/]+/, "")) +
        subRow("sing-box", origin + d.sub.singbox.replace(/^https?:\/\/[^/]+/, "")) +
        subRow("Player portal", origin + "/u/" + d.user.sub_token + "/") +
        '</div>' +

        '<div id="ctAct" class="hide">' +
        '<div class="tabs">' +
        ['24h','7d','30d'].map(function(w,i){
          return '<button class="tab' + (i===0?' on':'') + '" data-uw="' + w + '">' + w + '</button>';
        }).join("") +
        '</div><canvas class="graph" id="uG" style="height:150px"></canvas>' +
        '<div style="display:flex;gap:16px;margin-top:9px;font-size:11px;color:var(--muted)">' +
        '<span style="color:#00ffc8">— down</span>' +
        '<span style="color:#8b5cf6">— up</span></div>' +
        '<div id="uSum"></div></div>' +

        '<div id="ctAch" class="hide"><div class="achs">' +
        d.user.achievements.unlocked.map(function (a) {
          return achCard(a, true);
        }).concat(d.user.achievements.locked.map(function (a) {
          return achCard(a, false);
        })).join("") + '</div></div>' +

        '<div id="qrBox" style="text-align:center;margin-top:16px"></div>' +
        '<div class="acts"><button class="btn dim" onclick="ugClose()">Close</button></div>';

      $("#modalRoot .modal").innerHTML = html;
      var cfgs = d.configs;

      function hint() {
        var p = profs.filter(function (x) { return x.id === $("#pfSel").value; })[0];
        $("#pfHint").textContent = p ? p.desc : "";
      }
      hint();
      $("#pfSel").addEventListener("change", function () {
        S.profile = this.value; configModal(id);
      });
      $$("#modalRoot [data-ct]").forEach(function (b2) {
        b2.addEventListener("click", function () {
          $$("#modalRoot [data-ct]").forEach(function (x) { x.classList.remove("on"); });
          b2.classList.add("on");
          ["links", "sub", "act", "ach"].forEach(function (k) {
            $("#ct" + k.charAt(0).toUpperCase() + k.slice(1)).classList.toggle("hide", k !== b2.dataset.ct);
          });
        });
      });
      $$("#modalRoot [data-cp]").forEach(function (b3) {
        b3.addEventListener("click", function () { UG.copy(cfgs[+b3.dataset.cp].uri, b3); });
      });
      $$("#modalRoot [data-qr]").forEach(function (b4) {
        b4.addEventListener("click", function () {
          var uri = cfgs[+b4.dataset.qr].uri;
          var svg = QR.svg(uri, { size: 220, fg: "#000", bg: "#fff", quiet: 2 });
          $("#qrBox").innerHTML = svg
            ? '<div class="qr">' + svg + '</div><div style="font-size:10.5px;color:var(--muted);margin-top:8px">' +
              esc(cfgs[+b4.dataset.qr].label) + '</div>'
            : '<div style="color:var(--red);font-size:12px">Config too long for a QR code — use Copy.</div>';
          $("#qrBox").scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
      });
      $$("#modalRoot [data-sub]").forEach(function (b5) {
        b5.addEventListener("click", function () { UG.copy(b5.dataset.sub, b5); });
      });
      $$("#modalRoot [data-subqr]").forEach(function (b6) {
        b6.addEventListener("click", function () {
          $("#qrBox").innerHTML = '<div class="qr">' + QR.svg(b6.dataset.subqr, { size: 220 }) + '</div>';
          $("#qrBox").scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
      });

      // per-user activity chart (idea #4)
      loadUserChart(id, "24h");
      $$("#modalRoot [data-uw]").forEach(function (b7) {
        b7.addEventListener("click", function () {
          $$("#modalRoot [data-uw]").forEach(function (x) { x.classList.remove("on"); });
          b7.classList.add("on");
          loadUserChart(id, b7.dataset.uw);
        });
      });

      // boost controls (idea #7)
      wireBoost(id, d.user);
      var wk = $("#wkBtn");
      if (wk) wk.addEventListener("click", function () { weeklyModal(id); });
    }).catch(function (e) {
      $("#modalRoot .modal").innerHTML = '<h3>' + t("error") + '</h3><p>' + esc(e.message) +
        '</p><div class="acts"><button class="btn dim" onclick="ugClose()">Close</button></div>';
    });
  }

  function subRow(name, url) {
    return '<div class="cfg"><div class="info"><div class="nm">' + esc(name) + '</div>' +
      '<div class="pt" style="word-break:break-all">' + esc(url) + '</div></div>' +
      '<button class="btn sm" data-sub="' + esc(url) + '">' + t("copy") + '</button>' +
      '<button class="btn sm dim" data-subqr="' + esc(url) + '">' + t("qr") + '</button></div>';
  }

  function achCard(a, got) {
    return '<div class="ach' + (got ? " got" : "") + '"><span class="em">' + esc(a.icon) + '</span>' +
      '<div class="t"><b>' + esc(a.title) + '</b><span>' + esc(a.desc) + '</span></div></div>';
  }

  // ══ EVENT DELEGATION ════════════════════════════════════════════════
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-act]");
    if (el) {
      var id = +el.dataset.id;
      var u = S.users.filter(function (x) { return x.id === id; })[0];
      if (el.dataset.act === "cfg") configModal(id);
      else if (el.dataset.act === "wk") weeklyModal(id);
      else if (el.dataset.act === "edit") userModal(u);
      else if (el.dataset.act === "del") {
        if (!confirm(t("confirmdel") + "\n\n" + (u ? u.username : ""))) return;
        api("/api/users/" + id, { method: "DELETE" })
          .then(function () { UG.toast("🗑 deleted", "ok"); refreshUsers(); })
          .catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
      }
      return;
    }
    if (e.target.id === "addU") userModal(null);
    if (e.target.id === "newTrial") trialModal();
    if (e.target.id === "pingAll") pingAllGames();

    var th = e.target.closest("[data-th]");
    if (th) {
      UG.setTheme(th.dataset.th);
      render();
      UG.toast("🎨 Theme applied", "ok", 1400);
      return;
    }
    if (e.target.id === "applyCustom") {
      UG.setTheme("custom", $("#cc1").value, $("#cc2").value);
      render(); UG.toast("🎨 Custom theme applied", "ok", 1400);
      return;
    }

    var pg = e.target.closest("[data-pg]");
    if (pg) { pingGame(pg.dataset.pg); return; }

    var tcp = e.target.closest("[data-tcp]");
    if (tcp) { UG.copy(tcp.dataset.tcp, tcp); return; }
    var tqr = e.target.closest("[data-tqr]");
    if (tqr) {
      var box = $("#trialQr");
      if (box) {
        box.innerHTML = '<div class="qr">' + QR.svg(tqr.dataset.tqr, { size: 210 }) + '</div>';
        box.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      return;
    }
    var tt = e.target.closest("[data-tt]");
    if (tt) {
      api("/api/trials/" + tt.dataset.tt, {
        method: "POST", body: { enabled: tt.dataset.en === "1" }
      }).then(function () { loadTrials(); })
        .catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
      return;
    }
    var td = e.target.closest("[data-td]");
    if (td) {
      if (!confirm("Delete this trial link?")) return;
      api("/api/trials/" + td.dataset.td, { method: "DELETE" })
        .then(function () { UG.toast("🗑 deleted", "ok"); loadTrials(); })
        .catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
      return;
    }
    if (e.target.id === "evR") loadEvents();
    if (e.target.id === "raceBtn") runRace();
    if (e.target.id === "wsRaceBtn") runWsRace();
    if (e.target.id === "expJ") dl("/api/export?format=json");

    // ── country exits: activate / deactivate ────────────────────────
    var la = e.target.closest("[data-loc]");
    if (la) {
      if (la.dataset.locact === "start" &&
          !confirm("Start " + la.dataset.loc.toUpperCase() +
                   "? (~40MB RAM, minutes to verify)")) return;
      locAction(la.dataset.loc, la.dataset.locact);
      return;
    }
    // ── country exits: pin / unpin an exit IP ───────────────────────
    var lp = e.target.closest("[data-locpin]");
    if (lp) {
      if (lp.dataset.ip && !confirm(t("pinwarn") + "\n\n" +
                                    "Pin " + lp.dataset.ip + "?")) return;
      locAction(lp.dataset.locpin, lp.dataset.ip ? "pin" : "unpin",
                lp.dataset.ip ? { ip: lp.dataset.ip } : {});
      return;
    }
    if (e.target.id === "expC") dl("/api/export?format=csv");
    if (e.target.dataset && e.target.dataset.win) {
      S.window = e.target.dataset.win; render(); loadHistory();
    }
    if (e.target.id === "turboBtn") {
      var on = !(S.boot.settings || {}).turbo_mode;
      api("/api/settings", { method: "POST", body: { turbo_mode: on } })
        .then(function (st) {
          S.boot.settings = st; render();
          UG.toast(on ? "⚡ Turbo enabled — Xray reloaded" : "Turbo disabled", "ok");
        }).catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
    }
    if (e.target.id === "reloadBtn") {
      var b = e.target; b.disabled = true; b.innerHTML = '<span class="sp"></span>';
      api("/api/xray/reload", { method: "POST", body: {} })
        .then(function (r) {
          UG.toast(r.ok ? "✅ Xray reloaded" : "⚠️ " + esc(r.message), r.ok ? "ok" : "err");
        }).catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); })
        .then(function () { b.disabled = false; b.textContent = "↻ " + t("reload"); });
    }
    if (e.target.id === "saveAl") {
      api("/api/settings", {
        method: "POST",
        body: { alert_cpu: +$("#alCpu").value, alert_quota_pct: +$("#alQ").value }
      }).then(function (st) { S.boot.settings = st; UG.toast("✅ saved", "ok"); })
        .catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
    }
    if (e.target.dataset && e.target.dataset.sf != null) {
      api("/api/settings", {
        method: "POST",
        body: { smart_fragment: e.target.dataset.sf }
      }).then(function (st) {
        S.boot.settings = st;
        UG.toast("🧩 " + t("smartfragment") + " — " +
                 (st.smart_fragment || t("sfoff")), "ok");
        render();
      }).catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
      return;
    }
    if (e.target.id === "cfIpsSave") {
      api("/api/settings", {
        method: "POST",
        body: { cf_ips: $("#cfIps").value }
      }).then(function (st) {
        S.boot.settings = st;
        UG.toast("📌 " + t("cfips") + " — " + t("copied"), "ok");
      }).catch(function (er) { UG.toast("❌ " + esc(er.message), "err"); });
    }
    if (e.target.id === "cfIpsCheck") {
      var btn = e.target, box = $("#cfIpsRes");
      btn.disabled = true; btn.innerHTML = '<span class="sp"></span>';
      api("/api/ipcheck").then(function (d) {
        box.innerHTML = (d.ips || []).map(function (r) {
          return '<div class="kv"><b>' + esc(r.ip) + '</b><span style="color:' +
            (r.reachable ? "var(--green)" : "var(--red)") + '">' +
            (r.reachable ? r.ms + " ms" : "unreachable") + '</span></div>';
        }).join("") || '<div class="empty">—</div>';
      }).catch(function (er) {
        box.innerHTML = '<span style="color:var(--red)">' + esc(er.message) + '</span>';
      }).then(function () {
        btn.disabled = false; btn.textContent = t("cfipscheck");
      });
    }
    if (e.target.id === "realityToggle") {
      var on = !((S.boot.reality||{}).enabled);
      api("/api/settings", {method:"POST", body:{reality_enabled:on}}).then(function(st){
        S.boot.settings=st; return api("/api/reality").then(function(r){ S.boot.reality=r; render(); UG.toast(on?"REALITY enabled — Xray reloaded":"REALITY disabled","ok"); });
      }).catch(function(er){ UG.toast(esc(er.message),"err"); });
    }
    if (e.target.id === "rSave") {
      var body={reality_dest:$("#rDest").value.trim(), reality_sni:$("#rSni").value.trim(), reality_fp:$("#rFp").value, reality_port:$("#rPort").value.trim(), reality_host:$("#rHost").value.trim()};
      api("/api/settings", {method:"POST", body:body}).then(function(st){ S.boot.settings=st; UG.toast("REALITY saved","ok"); $("#rMsg").textContent="Saved."; }).catch(function(er){ $("#rMsg").textContent=er.message; UG.toast(esc(er.message),"err"); });
    }
    if (e.target.id === "rRotate") {
      if(!confirm("Rotate REALITY keys? All existing REALITY links will break.")) return;
      api("/api/reality/rotate", {method:"POST", body:{}}).then(function(){ return api("/api/reality").then(function(r){ S.boot.reality=r; render(); UG.toast("Keys rotated — Xray reloaded","ok"); }); }).catch(function(er){ UG.toast(esc(er.message),"err"); });
    }
  });

  // ── country search box (locations page) ─────────────────────────────
  document.addEventListener("input", function (e) {
    if (e.target && e.target.id === "locSearch") {
      S.locSearch = e.target.value;
      render();
    }
  });

  function dl(url) {
    fetch(url, { headers: { Authorization: "Bearer " + UG.token() } })
      .then(function (r) { return r.blob(); })
      .then(function (b) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(b);
        a.download = url.indexOf("csv") > 0 ? "players.csv" : "players.json";
        a.click(); URL.revokeObjectURL(a.href);
      });
  }

  // re-paint graphs on resize
  var rt;
  addEventListener("resize", function () {
    clearTimeout(rt);
    rt = setTimeout(function () { paintLive(); paintHistory(); }, 160);
  });

  // periodic refresh of the slower data
  setInterval(function () {
    if (!UG.token()) return;
    if (S.page === "dash") { loadEvents(); refreshUsers(); }
  }, 30000);

  // ══ GO ══════════════════════════════════════════════════════════════
  // Probe the server version before login so a stale cached bundle is
  // obvious straight away.
  // Guarded: a missing or throwing fetch must never stop the panel booting.
  (typeof fetch === "function"
    ? fetch("/api/meta?_=" + Date.now(), { cache: "no-store" })
    : Promise.reject(new Error("no fetch")))
    .then(function (r) { return r.json(); })
    .then(function (meta) {
      var sv = meta && meta.version;
      var tag = $("#loginVer");
      if (!tag) return;
      if (!sv) {
        tag.innerHTML = "server build is older than v3.1.0";
        tag.style.color = "var(--red)";
        return;
      }
      if (baseVer(ASSET_VERSION) !== sv) {
        tag.innerHTML = "cached v" + ASSET_VERSION + " · server v" + sv +
          ' — <a href="#" onclick="UG.hardReload();return false">reload</a>';
        tag.style.color = "var(--amber)";
      } else {
        tag.textContent = "v" + sv;
        tag.style.color = "var(--muted)";
      }
    })
    .catch(function () {});

  applyI18n();
  if (UG.token()) {
    api("/api/bootstrap").then(function () { start(); })
      .catch(function () { UG.setToken(""); });
  }
  setTimeout(function () { if (S.page === "dash" && S.boot) loadEvents(); }, 900);
})();

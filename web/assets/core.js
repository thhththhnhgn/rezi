/* ULTRA GAMING VPN — shared runtime (i18n, api, format, toast, charts) */
(function (G) {
  "use strict";

  // ── i18n ───────────────────────────────────────────────────────────
  var STR = {
    en: {
      dashboard: "Dashboard", users: "Players", configs: "Configs",
      analytics: "Analytics", race: "Latency Race", console: "Console",
      settings: "Settings", logout: "Logout", login: "Sign in",
      username: "Username", password: "Password",
      cpu: "CPU Load", ram: "Memory", sessions: "Active Sessions",
      uptime: "Uptime", score: "Gaming Score", download: "Download",
      upload: "Upload", netspeed: "Network Throughput",
      totaltraffic: "Total Traffic", topusers: "Top Players",
      events: "Event Log", addplayer: "New Player", quota: "Quota",
      used: "Used", expires: "Expires", status: "Status", actions: "",
      rank: "Rank", copy: "Copy", copied: "Copied!", qr: "QR",
      never: "Never", unlimited: "Unlimited", enabled: "Active",
      disabled: "Suspended", expired: "Expired", days: "days",
      turbo: "Turbo Mode", turbodesc: "Zero-buffer low-latency tuning",
      reload: "Reload Xray", save: "Save", cancel: "Cancel",
      delete: "Delete", edit: "Edit", reset: "Rotate keys",
      confirmdel: "Delete this player permanently?",
      noplayers: "No players yet", achievements: "Achievements",
      profile: "Game Profile", subscription: "Subscription",
      heatmap: "Traffic Heatmap", history: "History",
      startrace: "Start Race", racing: "Measuring...",
      winner: "Fastest route", online: "ONLINE", offline: "OFFLINE",
      xray: "Xray Core", export: "Export", theme: "Theme",
      loading: "Loading...", error: "Something went wrong",
      theme: "Theme", boost: "Boost", boostdesc: "30 minutes of zero-buffer, priority tuning",
      boostactive: "BOOST ACTIVE", boostoff: "Activate Boost",
      gameping: "Game Server Ping", testping: "Test all",
      weekly: "Weekly Report", trials: "Trial Links",
      locations: "Country Exits",
      newtrial: "New trial link", claims: "Claims", perday: "Per day",
      usage: "Usage", noData: "No data yet", myactivity: "My Activity",
      activate: "Activate", deactivate: "Deactivate",
      search: "Search countries…", pin: "Pin", unpin: "Unpin",
      pinned: "PINNED", exitip: "Exit IP", bestexits: "Most stable exits",
      stability: "stability", sessions: "sessions", active: "active",
      ramnote: "Each country runs its own Tor instance (~40 MB RAM).",
      maxnote: "At most", pinwarn: "Pinning forces every connection through one relay. If it goes down, this location fails until you unpin.",
      pinhint: "Tor rotates exits on its own; these are the ones that served longest. Pin one for a stable IP.",
      exitnote: "Routes via Tor — 500ms+ latency. Not for gaming.",
      locstatus: "Status", torunavail: "Tor is not installed in this image.",
      wsrace: "Tunnel WS", wsstart: "Measure via WebSocket",
      wsdesc: "Round-trip over the real tunnel (WebSocket echo), 8 samples.",
      nostable: "No stable exits tracked yet.",
      exitcount: "countries with Tor exit relays",
      relaylive: "live data · updated", relaybundled: "bundled snapshot",
      cfips: "Pinned CDN IPs",
      cfipsdesc: "Configs that dial a fixed IP while keeping your hostname as SNI. If an ISP blocks the hostname, players can switch to these. Only works when the hostname is proxied through a CDN that routes by SNI (e.g. Cloudflare). The SNI itself can never be a foreign site — TLS is terminated for your hostname.",
      cfipscheck: "Check from server",
      smartfragment: "Smart Fragment",
      sfdesc: "Splits only the TLS ClientHello into pieces with tiny pauses — the standard way to slip past SNI-based DPI on strict operators. Works on v2rayNG / NekoBox / v2rayN links (Clash & sing-box don't support it). A small per-connection cost, so pick the lightest mode that connects.",
      sfoff: "Off",
      sflight: "Light", sfmedium: "Medium", sfaggressive: "Aggressive",
    },
    fa: {
      dashboard: "داشبورد", users: "کاربران", configs: "کانفیگ‌ها",
      analytics: "آمار", race: "مسابقه پینگ", console: "کنسول",
      settings: "تنظیمات", logout: "خروج", login: "ورود",
      username: "نام کاربری", password: "رمز عبور",
      cpu: "پردازنده", ram: "حافظه", sessions: "اتصال فعال",
      uptime: "آپتایم", score: "امتیاز گیمینگ", download: "دانلود",
      upload: "آپلود", netspeed: "سرعت شبکه",
      totaltraffic: "ترافیک کل", topusers: "پرمصرف‌ترین‌ها",
      events: "رویدادها", addplayer: "کاربر جدید", quota: "سهمیه",
      used: "مصرف", expires: "انقضا", status: "وضعیت", actions: "",
      rank: "رنک", copy: "کپی", copied: "کپی شد!", qr: "کیوآر",
      never: "هرگز", unlimited: "نامحدود", enabled: "فعال",
      disabled: "غیرفعال", expired: "منقضی", days: "روز",
      turbo: "حالت توربو", turbodesc: "تنظیم بدون بافر برای کمترین تاخیر",
      reload: "ری‌استارت Xray", save: "ذخیره", cancel: "انصراف",
      delete: "حذف", edit: "ویرایش", reset: "تعویض کلیدها",
      confirmdel: "این کاربر برای همیشه حذف شود؟",
      noplayers: "هنوز کاربری نیست", achievements: "دستاوردها",
      profile: "پروفایل بازی", subscription: "اشتراک",
      heatmap: "نقشه حرارتی ترافیک", history: "تاریخچه",
      startrace: "شروع مسابقه", racing: "در حال سنجش...",
      winner: "سریع‌ترین مسیر", online: "آنلاین", offline: "آفلاین",
      xray: "هسته Xray", export: "خروجی", theme: "تم",
      loading: "در حال بارگذاری...", error: "خطایی رخ داد",
      theme: "پوسته", boost: "بوست", boostdesc: "۳۰ دقیقه تنظیم بدون بافر و اولویت‌دار",
      boostactive: "بوست فعال است", boostoff: "فعال‌سازی بوست",
      gameping: "پینگ سرور بازی‌ها", testping: "تست همه",
      weekly: "گزارش هفتگی", trials: "لینک‌های تست",
      locations: "خروجی کشورها",
      newtrial: "لینک تست جدید", claims: "دریافت‌ها", perday: "روزانه",
      usage: "مصرف", noData: "هنوز داده‌ای نیست", myactivity: "فعالیت من",
      activate: "فعال‌سازی", deactivate: "غیرفعال‌سازی",
      search: "جستجوی کشورها…", pin: "پین", unpin: "لغو پین",
      pinned: "پین‌شده", exitip: "آی‌پی خروجی", bestexits: "پایدارترین خروجی‌ها",
      stability: "پایداری", sessions: "اتصال", active: "فعال",
      ramnote: "هر کشور یک نمونه‌ی تور جدا (~۴۰ مگابایت رم) اجرا می‌کنه.",
      maxnote: "حداکثر", pinwarn: "پین کردن همه‌ی اتصال‌ها رو از یک رله عبور می‌ده. اگه اون رله از دست بره، این لوکیشن تا لغو پین کار نمی‌کنه.",
      pinhint: "تور خودش خروجی رو عوض می‌کنه؛ این‌ها طولانی‌ترین‌هایی هستن که کار کردن. برای آی‌پی ثابت یکی رو پین کن.",
      exitnote: "مسیر از تور می‌گذره — تأخیر ۵۰۰ms+. برای بازی نیست.",
      locstatus: "وضعیت", torunavail: "تور توی این تصویر نصب نیست.",
      wsrace: "تونل WS", wsstart: "سنجش از طریق وب‌سوکت",
      wsdesc: "رفت‌وبرگشت روی تونل واقعی (اکوی وب‌سوکت)، ۸ نمونه.",
      nostable: "هنوز خروجی پایداری ثبت نشده.",
      exitcount: "کشور دارای رله‌ی خروجی تور",
      relaylive: "داده‌ی زنده · به‌روز شده", relaybundled: "داده‌ی داخلی",
      cfips: "آی‌پی ثابت (CDN IP)",
      cfipsdesc: "کانفیگ‌هایی که با یک آی‌پی ثابت وصل می‌شن ولی SNI همون دامنه‌ی خودته. اگه اپراتور دامنه رو مسدود کنه، بازیکن‌ها می‌تونن از این‌ها استفاده کنن. فقط وقتی کار می‌کنه که دامنه پشت یه CDN باشه که بر اساس SNI مسیردهی می‌کنه (مثل Cloudflare). خودِ SNI هیچ‌وقت نمی‌تونه سایت خارجی باشه — TLS برای دامنه‌ی خودت صادر شده.",
      cfipscheck: "بررسی از سرور",
      smartfragment: "فرگمنت هوشمند",
      sfdesc: "فقط TLS ClientHello رو تکه‌تکه می‌کنه با مکث‌های خیلی کوتاه — روش استاندارد رد شدن از DPI اپراتورهای سخت‌گیر. روی لینک‌های v2rayNG / NekoBox / v2rayN کار می‌کنه (Clash و sing-box پشتیبانی نمی‌کنن). هزینه‌ش به‌ازای هر اتصال کمه؛ پس سبک‌ترین حالتی که وصل شد رو انتخاب کن.",
      sfoff: "خاموش",
      sflight: "سبک", sfmedium: "متوسط", sfaggressive: "تهاجمی",
    }
  };

  var lang = localStorage.getItem("ug_lang") || "en";
  // apply the saved theme as early as possible to avoid a colour flash
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { applyTheme(); });
  } else {
    setTimeout(function () { applyTheme(); }, 0);
  }
  function t(k) { return (STR[lang] && STR[lang][k]) || STR.en[k] || k; }
  function setLang(l) {
    lang = l; localStorage.setItem("ug_lang", l);
    if (document.body) document.body.setAttribute("dir", l === "fa" ? "rtl" : "ltr");
    if (document.documentElement) document.documentElement.lang = l;
    G.dispatchEvent(new CustomEvent("ug:lang"));
  }
  function curLang() { return lang; }

  // ── format ─────────────────────────────────────────────────────────
  function bytes(n, dp) {
    n = Number(n) || 0;
    var u = ["B", "KB", "MB", "GB", "TB", "PB"], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return n.toFixed(i === 0 ? 0 : (dp == null ? 1 : dp)) + " " + u[i];
  }
  function speed(bps) { return bytes(bps, 1) + "/s"; }
  function num(n) { return (Number(n) || 0).toLocaleString(); }
  function when(ts) {
    if (!ts) return t("never");
    var d = new Date(ts * 1000);
    return d.toLocaleDateString(lang === "fa" ? "fa-IR" : undefined,
      { year: "numeric", month: "short", day: "numeric" });
  }
  function ago(ts) {
    if (!ts) return "—";
    var s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m";
    if (s < 86400) return Math.floor(s / 3600) + "h";
    return Math.floor(s / 86400) + "d";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ── api ────────────────────────────────────────────────────────────
  var TOKEN_KEY = "ug_token";
  function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
  function setToken(v) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); }

  function api(path, opts) {
    opts = opts || {};
    var h = opts.headers || {};
    if (token()) h["Authorization"] = "Bearer " + token();
    if (opts.body != null && typeof opts.body !== "string") {
      h["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    opts.headers = h;
    return fetch(path, opts).then(function (r) {
      if (r.status === 401) { setToken(""); location.reload(); throw new Error("unauthorized"); }
      var ct = r.headers.get("content-type") || "";
      var p = ct.indexOf("json") >= 0 ? r.json() : r.text();
      return p.then(function (d) {
        if (!r.ok) throw new Error((d && d.error) || r.status + " " + r.statusText);
        return d;
      });
    });
  }

  // ── toast ──────────────────────────────────────────────────────────
  function toast(msg, kind, ms) {
    var box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
    var el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.innerHTML = msg;
    box.appendChild(el);
    setTimeout(function () {
      el.style.transition = "opacity .25s,transform .25s";
      el.style.opacity = "0"; el.style.transform = "translateX(60px)";
      setTimeout(function () { el.remove(); }, 260);
    }, ms || 3200);
  }

  // ── clipboard ──────────────────────────────────────────────────────
  function copy(text, btn) {
    function done() {
      if (btn) {
        var old = btn.textContent;
        btn.textContent = t("copied"); btn.classList.add("ok");
        setTimeout(function () { btn.textContent = old; btn.classList.remove("ok"); }, 1600);
      } else toast(t("copied"), "ok", 1500);
    }
    if (navigator.clipboard && G.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(text, done); });
    } else fallback(text, done);
  }
  function fallback(text, cb) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); cb(); } catch (e) { toast("Copy failed", "err"); }
    ta.remove();
  }

  // ── charts (canvas, no deps) ───────────────────────────────────────
  function hidpi(cv) {
    var dpr = G.devicePixelRatio || 1;
    var w = cv.clientWidth || cv.offsetWidth || 300;
    var h = cv.clientHeight || cv.offsetHeight || 150;
    if (cv.width !== w * dpr || cv.height !== h * dpr) {
      cv.width = w * dpr; cv.height = h * dpr;
    }
    var ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }

  function sparkline(cv, series, opts) {
    opts = opts || {};
    var g = hidpi(cv), ctx = g.ctx, W = g.w, H = g.h;
    ctx.clearRect(0, 0, W, H);
    var all = [];
    series.forEach(function (s) { all = all.concat(s.data); });
    var max = Math.max.apply(null, all.concat([opts.min || 1]));
    var pad = 3;

    ctx.strokeStyle = "rgba(255,255,255,.05)"; ctx.lineWidth = 1;
    for (var i = 1; i < 4; i++) {
      ctx.beginPath(); ctx.moveTo(0, H / 4 * i); ctx.lineTo(W, H / 4 * i); ctx.stroke();
    }

    series.forEach(function (s) {
      var d = s.data, n = d.length;
      if (n < 2) return;
      var pts = d.map(function (v, i) {
        return [i / (n - 1) * W, H - (v / max) * (H - pad * 2) - pad];
      });
      if (opts.fill !== false) {
        var grad = ctx.createLinearGradient(0, 0, 0, H);
        grad.addColorStop(0, s.color + "44"); grad.addColorStop(1, s.color + "00");
        ctx.beginPath(); ctx.moveTo(pts[0][0], H);
        pts.forEach(function (p) { ctx.lineTo(p[0], p[1]); });
        ctx.lineTo(pts[n - 1][0], H); ctx.closePath();
        ctx.fillStyle = grad; ctx.fill();
      }
      ctx.beginPath(); ctx.strokeStyle = s.color; ctx.lineWidth = 2;
      ctx.shadowColor = s.color; ctx.shadowBlur = 7; ctx.lineJoin = "round";
      pts.forEach(function (p, i) { i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); });
      ctx.stroke(); ctx.shadowBlur = 0;
    });
  }

  function gauge(cv, value, color) {
    var g = hidpi(cv), ctx = g.ctx, W = g.w, H = g.h;
    ctx.clearRect(0, 0, W, H);
    var cx = W / 2, cy = H / 2, r = Math.min(W, H) / 2 - 9;
    var start = Math.PI * 0.75, end = Math.PI * 2.25;
    var v = Math.max(0, Math.min(100, value)) / 100;

    ctx.beginPath(); ctx.arc(cx, cy, r, start, end);
    ctx.strokeStyle = "rgba(255,255,255,.07)"; ctx.lineWidth = 9;
    ctx.lineCap = "round"; ctx.stroke();

    ctx.beginPath(); ctx.arc(cx, cy, r, start, start + (end - start) * v);
    ctx.strokeStyle = color; ctx.lineWidth = 9; ctx.lineCap = "round";
    ctx.shadowColor = color; ctx.shadowBlur = 13; ctx.stroke(); ctx.shadowBlur = 0;

    ctx.fillStyle = color; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = "900 " + Math.round(r * 0.62) + "px 'Share Tech Mono',monospace";
    ctx.fillText(Math.round(value), cx, cy - r * 0.05);
    ctx.fillStyle = "rgba(255,255,255,.35)";
    ctx.font = "600 " + Math.round(r * 0.2) + "px 'Exo 2',sans-serif";
    ctx.fillText("/100", cx, cy + r * 0.42);
  }

  function scoreColor(v) {
    return v >= 85 ? "#00ffc8" : v >= 70 ? "#2ed573" : v >= 50 ? "#ffa502" : "#ff4757";
  }

  // ── particles background ───────────────────────────────────────────
  function particles(cv) {
    if (!cv) return;
    if (G.matchMedia && G.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var ctx = cv.getContext("2d"), ps = [], raf;
    function resize() {
      var dpr = Math.min(G.devicePixelRatio || 1, 2);
      cv.width = innerWidth * dpr; cv.height = innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    function seed() {
      var n = Math.min(46, Math.round(innerWidth / 26));
      ps = [];
      for (var i = 0; i < n; i++) ps.push({
        x: Math.random() * innerWidth, y: Math.random() * innerHeight,
        vx: (Math.random() - .5) * .22, vy: (Math.random() - .5) * .22,
        r: Math.random() * 1.6 + .5
      });
    }
    function tick() {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      for (var i = 0; i < ps.length; i++) {
        var p = ps[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > innerWidth) p.vx *= -1;
        if (p.y < 0 || p.y > innerHeight) p.vy *= -1;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7);
        ctx.fillStyle = "rgba(0,255,200,.32)"; ctx.fill();
        for (var j = i + 1; j < ps.length; j++) {
          var q = ps[j], dx = p.x - q.x, dy = p.y - q.y, d = dx * dx + dy * dy;
          if (d < 15000) {
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
            ctx.strokeStyle = "rgba(0,255,200," + (0.1 * (1 - d / 15000)) + ")";
            ctx.lineWidth = .6; ctx.stroke();
          }
        }
      }
      raf = requestAnimationFrame(tick);
    }
    resize(); seed(); tick();
    addEventListener("resize", function () { resize(); seed(); });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) cancelAnimationFrame(raf); else tick();
    });
  }

  // ── count-up animation ─────────────────────────────────────────────
  function countTo(el, to, fmt, ms) {
    if (!el) return;
    var from = parseFloat(el.dataset.v || "0");
    if (from === to) { el.innerHTML = fmt(to); return; }
    var t0 = performance.now(), dur = ms || 420;
    el.dataset.v = to;
    (function step(now) {
      var k = Math.min(1, (now - t0) / dur);
      k = 1 - Math.pow(1 - k, 3);
      el.innerHTML = fmt(from + (to - from) * k);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }


  // ── themes (idea #10) ──────────────────────────────────────────────
  var THEMES = [
    { id: "neon",      label: "Neon",      c1: "#00ffc8", c2: "#8b5cf6" },
    { id: "matrix",    label: "Matrix",    c1: "#00ff41", c2: "#008f11" },
    { id: "cyberpunk", label: "Cyberpunk", c1: "#fcee0a", c2: "#ff003c" },
    { id: "ice",       label: "Ice",       c1: "#5eead4", c2: "#3b82f6" },
    { id: "ember",     label: "Ember",     c1: "#ff7a18", c2: "#af002d" },
    { id: "royal",     label: "Royal",     c1: "#a78bfa", c2: "#f472b6" },
    { id: "stealth",   label: "Stealth",   c1: "#9ca3af", c2: "#6b7280" }
  ];

  function theme() { return localStorage.getItem("ug_theme") || "neon"; }

  function setTheme(id, c1, c2) {
    localStorage.setItem("ug_theme", id);
    if (id === "custom") {
      localStorage.setItem("ug_c1", c1 || "#00ffc8");
      localStorage.setItem("ug_c2", c2 || "#8b5cf6");
    }
    applyTheme();
    G.dispatchEvent(new CustomEvent("ug:theme"));
  }

  function applyTheme() {
    var id = theme(), b = document.body;
    if (!b) return;
    if (id === "neon") b.removeAttribute("data-theme");
    else b.setAttribute("data-theme", id);
    if (id === "custom") {
      b.style.setProperty("--c1", localStorage.getItem("ug_c1") || "#00ffc8");
      b.style.setProperty("--c2", localStorage.getItem("ug_c2") || "#8b5cf6");
    } else {
      b.style.removeProperty("--c1");
      b.style.removeProperty("--c2");
    }
    var t = THEMES.filter(function (x) { return x.id === id; })[0];
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta && t) meta.setAttribute("content", t.c1);
  }

  // ── latency probing (shared by panel + portal) ─────────────────────
  /**
   * Probe a URL n times and return {median, jitter, min, max, loss}.
   * Cross-origin targets are probed with mode:"no-cors" — the response is
   * opaque, which is fine because we only ever measure elapsed time.
   */
  function probe(url, n, onTick) {
    n = n || 6;
    var samples = [], fails = 0;
    var sameOrigin = url.charAt(0) === "/";
    var chain = Promise.resolve();

    for (var i = 0; i < n; i++) {
      (function (k) {
        chain = chain.then(function () {
          return new Promise(function (resolve) {
            var t0 = performance.now(), done = false;
            var timer = setTimeout(function () {
              if (!done) { done = true; fails++; resolve(); }
            }, 4000);
            var sep = url.indexOf("?") > 0 ? "&" : "?";
            fetch(url + sep + "_=" + Date.now() + "-" + k, {
              cache: "no-store",
              mode: sameOrigin ? "same-origin" : "no-cors",
              redirect: "follow"
            }).then(function () {
              if (done) return;
              done = true; clearTimeout(timer);
              samples.push(performance.now() - t0);
              if (onTick) onTick(k + 1, n);
              resolve();
            }).catch(function () {
              if (done) return;
              done = true; clearTimeout(timer); fails++;
              if (onTick) onTick(k + 1, n);
              resolve();
            });
          });
        }).then(function () {
          return new Promise(function (r) { setTimeout(r, 60); });
        });
      })(i);
    }

    return chain.then(function () {
      if (!samples.length) return { median: null, loss: 100 };
      samples.sort(function (a, b) { return a - b; });
      var mid = samples[Math.floor(samples.length / 2)];
      var avg = samples.reduce(function (a, b) { return a + b; }, 0) / samples.length;
      var jit = Math.sqrt(samples.reduce(function (a, b) {
        return a + Math.pow(b - avg, 2);
      }, 0) / samples.length);
      return {
        median: Math.round(mid), jitter: Math.round(jit),
        min: Math.round(samples[0]), max: Math.round(samples[samples.length - 1]),
        loss: Math.round(fails / n * 100)
      };
    });
  }

  /**
   * Probe RTT over a real WebSocket echo (the /__ws tunnel path).
   * Opens one connection, bounces n frames, returns the same stats shape
   * as probe() so callers can render them identically.
   */
  function wsProbe(url, n, onTick) {
    n = n || 8;
    return new Promise(function (resolve) {
      var samples = [], fails = 0, sent = 0, t0 = 0, ws, to, closed = false;
      function finish() {
        if (closed) return;
        closed = true;
        clearTimeout(to);
        try { if (ws) ws.close(); } catch (e) {}
        if (!samples.length) {
          return resolve({ median: null, jitter: 0, min: 0, max: 0, loss: 100 });
        }
        samples.sort(function (a, b) { return a - b; });
        var mid = samples[Math.floor(samples.length / 2)];
        var avg = samples.reduce(function (a, b) { return a + b; }, 0) / samples.length;
        var jit = Math.sqrt(samples.reduce(function (a, b) {
          return a + Math.pow(b - avg, 2);
        }, 0) / samples.length);
        resolve({
          median: Math.round(mid), jitter: Math.round(jit),
          min: Math.round(samples[0]), max: Math.round(samples[samples.length - 1]),
          loss: Math.round(fails / n * 100)
        });
      }
      function next() {
        if (closed) return;
        if (sent >= n) return finish();
        t0 = performance.now();
        try { ws.send("p"); sent++; } catch (e) { fails++; finish(); }
      }
      try {
        ws = new WebSocket(url);
      } catch (e) {
        return resolve({ median: null, jitter: 0, min: 0, max: 0, loss: 100 });
      }
      to = setTimeout(function () { fails = n - sent; finish(); }, 12000);
      ws.onopen = function () { next(); };
      ws.onmessage = function () {
        if (closed) return;
        samples.push(performance.now() - t0);
        if (onTick) onTick(sent, n);
        next();
      };
      ws.onerror = function () { if (!closed) { fails = n - sent; finish(); } };
      ws.onclose = function () { if (!closed) { fails = n - sent; finish(); } };
    });
  }

  function pingColor(ms) {
    if (ms == null) return "#ff4757";
    return ms < 60 ? "#2ed573" : ms < 120 ? "#00ffc8"
         : ms < 200 ? "#ffa502" : "#ff4757";
  }

  function pingVerdict(ms) {
    if (ms == null) return "unreachable";
    return ms < 60 ? "excellent" : ms < 120 ? "good"
         : ms < 200 ? "playable" : "high";
  }

  function mmss(sec) {
    sec = Math.max(0, Math.floor(sec));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  /**
   * Clear every client-side cache layer and reload.
   * Service workers and the HTTP cache can each independently pin an old
   * build, so both are cleared before reloading with a cache-busting param.
   */
  function hardReload() {
    var jobs = [];
    if (G.caches && caches.keys) {
      jobs.push(caches.keys().then(function (ks) {
        return Promise.all(ks.map(function (k) { return caches.delete(k); }));
      }).catch(function () {}));
    }
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      jobs.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
        return Promise.all(rs.map(function (r) { return r.unregister(); }));
      }).catch(function () {}));
    }
    Promise.all(jobs).then(function () {
      var u = new URL(location.href);
      u.searchParams.set("_cb", Date.now());
      location.replace(u.toString());
    });
  }

  G.UG = {
    t: t, setLang: setLang, lang: curLang, STR: STR,
    hardReload: hardReload,
    THEMES: THEMES, theme: theme, setTheme: setTheme, applyTheme: applyTheme,
    probe: probe, wsProbe: wsProbe,
    pingColor: pingColor, pingVerdict: pingVerdict, mmss: mmss,
    bytes: bytes, speed: speed, num: num, when: when, ago: ago, esc: esc,
    api: api, token: token, setToken: setToken,
    toast: toast, copy: copy,
    sparkline: sparkline, gauge: gauge, scoreColor: scoreColor,
    particles: particles, countTo: countTo, hidpi: hidpi
  };
})(window);

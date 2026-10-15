/*!
 * Minimal QR Code encoder (byte mode, ECC level M, auto version 1..20).
 * Self-contained — no CDN, works offline inside the PWA.
 * Renders to an SVG string or a canvas.
 */
(function (global) {
  "use strict";

  // ── Galois field ───────────────────────────────────────────────────
  var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x; LOG[x] = i;
      x <<= 1; if (x & 0x100) x ^= 0x11d;
    }
    for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
  })();
  function gmul(a, b) { return (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]]; }

  function rsPoly(deg) {
    var poly = [1];
    for (var i = 0; i < deg; i++) {
      var np = new Array(poly.length + 1).fill(0);
      for (var j = 0; j < poly.length; j++) {
        np[j] ^= gmul(poly[j], 1);
        np[j + 1] ^= gmul(poly[j], EXP[i]);
      }
      poly = np;
    }
    return poly;
  }

  function rsEncode(data, ecLen) {
    var gen = rsPoly(ecLen), res = new Array(ecLen).fill(0);
    for (var i = 0; i < data.length; i++) {
      var f = data[i] ^ res[0];
      res.shift(); res.push(0);
      if (f !== 0) for (var j = 0; j < gen.length - 1; j++) res[j] ^= gmul(gen[j + 1], f);
    }
    return res;
  }

  // ── Version tables (ECC level M) ───────────────────────────────────
  // [ total codewords, ec codewords per block, group1 blocks, group2 blocks ]
  var VER = [
    null,
    [26, 10, 1, 0], [44, 16, 1, 0], [70, 26, 1, 0], [100, 18, 2, 0],
    [134, 24, 2, 0], [172, 16, 4, 0], [196, 18, 4, 0], [242, 22, 2, 2],
    [292, 22, 3, 2], [346, 26, 4, 1], [404, 30, 1, 4], [466, 22, 6, 2],
    [532, 22, 8, 1], [581, 24, 4, 5], [655, 24, 5, 5], [733, 28, 7, 3],
    [815, 28, 10, 1], [901, 26, 9, 4], [991, 26, 3, 11], [1085, 26, 3, 13]
  ];
  var ALIGN = [
    [], [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34],
    [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50], [6, 30, 54],
    [6, 32, 58], [6, 34, 62], [6, 26, 46, 66], [6, 26, 48, 70],
    [6, 26, 50, 74], [6, 30, 54, 78], [6, 30, 56, 82], [6, 30, 58, 86],
    [6, 34, 62, 90]
  ];

  function capacity(v) {
    var t = VER[v], blocks = t[2] + t[3];
    return t[0] - t[1] * blocks;
  }

  function pickVersion(len) {
    for (var v = 1; v <= 20; v++) {
      var cci = v < 10 ? 8 : 16;
      var need = Math.ceil((4 + cci + len * 8) / 8);
      if (need <= capacity(v)) return v;
    }
    return -1;
  }

  // ── bit buffer ─────────────────────────────────────────────────────
  function Bits() { this.b = []; }
  Bits.prototype.put = function (val, len) {
    for (var i = len - 1; i >= 0; i--) this.b.push((val >>> i) & 1);
  };

  function encodeData(bytes, ver) {
    var cap = capacity(ver) * 8, bb = new Bits();
    bb.put(4, 4);                                   // byte mode
    bb.put(bytes.length, ver < 10 ? 8 : 16);
    for (var i = 0; i < bytes.length; i++) bb.put(bytes[i], 8);
    var term = Math.min(4, cap - bb.b.length);
    if (term > 0) bb.put(0, term);
    while (bb.b.length % 8) bb.b.push(0);
    var cw = [];
    for (var k = 0; k < bb.b.length; k += 8) {
      var v = 0;
      for (var j = 0; j < 8; j++) v = (v << 1) | bb.b[k + j];
      cw.push(v);
    }
    var pad = [0xEC, 0x11], p = 0;
    while (cw.length < capacity(ver)) cw.push(pad[p++ % 2]);
    return cw;
  }

  function interleave(cw, ver) {
    var t = VER[ver], ecLen = t[1], g1 = t[2], g2 = t[3];
    var total = g1 + g2, base = Math.floor(capacity(ver) / total);
    var blocks = [], ecs = [], off = 0;
    for (var i = 0; i < total; i++) {
      var size = base + (i >= g1 ? 1 : 0);
      var blk = cw.slice(off, off + size); off += size;
      blocks.push(blk); ecs.push(rsEncode(blk, ecLen));
    }
    var out = [], maxD = Math.max.apply(null, blocks.map(function (b) { return b.length; }));
    for (var d = 0; d < maxD; d++)
      for (var b = 0; b < blocks.length; b++)
        if (d < blocks[b].length) out.push(blocks[b][d]);
    for (var e = 0; e < ecLen; e++)
      for (var b2 = 0; b2 < ecs.length; b2++) out.push(ecs[b2][e]);
    return out;
  }

  // ── matrix ─────────────────────────────────────────────────────────
  function build(ver, data) {
    var n = ver * 4 + 17;
    var m = [], res = [];
    for (var i = 0; i < n; i++) { m.push(new Int8Array(n).fill(-1)); res.push(new Uint8Array(n)); }

    function finder(r, c) {
      for (var dr = -1; dr <= 7; dr++) for (var dc = -1; dc <= 7; dc++) {
        var rr = r + dr, cc = c + dc;
        if (rr < 0 || rr >= n || cc < 0 || cc >= n) continue;
        var on = (dr >= 0 && dr <= 6 && (dc === 0 || dc === 6)) ||
                 (dc >= 0 && dc <= 6 && (dr === 0 || dr === 6)) ||
                 (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4);
        m[rr][cc] = on ? 1 : 0; res[rr][cc] = 1;
      }
    }
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0);

    var al = ALIGN[ver];
    for (var a = 0; a < al.length; a++) for (var b = 0; b < al.length; b++) {
      var r0 = al[a], c0 = al[b];
      if ((r0 <= 7 && c0 <= 7) || (r0 <= 7 && c0 >= n - 8) || (r0 >= n - 8 && c0 <= 7)) continue;
      for (var dr2 = -2; dr2 <= 2; dr2++) for (var dc2 = -2; dc2 <= 2; dc2++) {
        var on2 = Math.max(Math.abs(dr2), Math.abs(dc2)) !== 1;
        m[r0 + dr2][c0 + dc2] = on2 ? 1 : 0; res[r0 + dr2][c0 + dc2] = 1;
      }
    }
    for (var i2 = 8; i2 < n - 8; i2++) {
      var v = i2 % 2 === 0 ? 1 : 0;
      if (!res[6][i2]) { m[6][i2] = v; res[6][i2] = 1; }
      if (!res[i2][6]) { m[i2][6] = v; res[i2][6] = 1; }
    }
    m[n - 8][8] = 1; res[n - 8][8] = 1;                 // dark module
    for (var f = 0; f < 9; f++) {
      if (f !== 6) { if (!res[8][f]) res[8][f] = 1; if (!res[f][8]) res[f][8] = 1; }
    }
    for (var f2 = 0; f2 < 8; f2++) { res[8][n - 1 - f2] = 1; res[n - 1 - f2][8] = 1; }

    if (ver >= 7) {
      var vb = verBits(ver);
      for (var i3 = 0; i3 < 18; i3++) {
        var bit = (vb >> i3) & 1, rr2 = Math.floor(i3 / 3), cc2 = i3 % 3;
        m[rr2][n - 11 + cc2] = bit; res[rr2][n - 11 + cc2] = 1;
        m[n - 11 + cc2][rr2] = bit; res[n - 11 + cc2][rr2] = 1;
      }
    }

    // place data, mask 0
    var dir = -1, row = n - 1, idx = 0, bitIdx = 0;
    for (var col = n - 1; col > 0; col -= 2) {
      if (col === 6) col--;
      for (;;) {
        for (var s = 0; s < 2; s++) {
          var cc3 = col - s;
          if (!res[row][cc3]) {
            var dark = 0;
            if (idx < data.length) dark = (data[idx] >>> (7 - bitIdx)) & 1;
            if ((row + cc3) % 2 === 0) dark ^= 1;       // mask pattern 0
            m[row][cc3] = dark; res[row][cc3] = 1;
            bitIdx++; if (bitIdx === 8) { bitIdx = 0; idx++; }
          }
        }
        row += dir;
        if (row < 0 || row >= n) { row -= dir; dir = -dir; break; }
      }
    }

    // Format info: ECC level M (binary 00) + mask pattern 0 -> 0x5412.
    // The 15 bits are written MSB-first; i = 0 is the most significant bit.
    var fmt = fmtBits(0x00, 0);
    for (var i4 = 0; i4 < 15; i4++) {
      var bit2 = (fmt >> (14 - i4)) & 1;

      // copy 1 — wraps around the top-left finder
      if (i4 < 6)        m[8][i4]       = bit2;
      else if (i4 === 6) m[8][7]        = bit2;
      else if (i4 === 7) m[8][8]        = bit2;
      else if (i4 === 8) m[7][8]        = bit2;
      else               m[14 - i4][8]  = bit2;

      // copy 2 — bottom-left column, then top-right row
      if (i4 < 7) m[n - 1 - i4][8]  = bit2;
      else        m[8][n - 15 + i4] = bit2;
    }
    for (var r3 = 0; r3 < n; r3++) for (var c3 = 0; c3 < n; c3++) if (m[r3][c3] < 0) m[r3][c3] = 0;
    return m;
  }

  function fmtBits(ec, mask) {
    var d = ((ec << 3) | mask) << 10, v = d;
    for (var i = 4; i >= 0; i--) if (v & (1 << (i + 10))) v ^= 0x537 << i;
    return ((d | v) ^ 0x5412);
  }
  function verBits(ver) {
    var d = ver << 12, v = d;
    for (var i = 5; i >= 0; i--) if (v & (1 << (i + 12))) v ^= 0x1f25 << i;
    return d | v;
  }

  function utf8(str) {
    if (typeof TextEncoder !== 'undefined') return Array.from(new TextEncoder().encode(str));
    // fallback for very old engines
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
      else if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        var cp = 0x10000 + ((c - 0xd800) << 10) + (str.charCodeAt(++i) - 0xdc00);
        out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f),
                 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
      } else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    }
    return out;
  }

  function matrix(text) {
    var bytes = utf8(text);
    var ver = pickVersion(bytes.length);
    if (ver < 0) return null;                    // too long for v20/M
    return build(ver, interleave(encodeData(bytes, ver), ver));
  }

  function svg(text, opts) {
    opts = opts || {};
    var m = matrix(text);
    if (!m) return '';
    var n = m.length, q = opts.quiet == null ? 2 : opts.quiet, size = n + q * 2;
    var d = '';
    for (var r = 0; r < n; r++) for (var c = 0; c < n; c++)
      if (m[r][c]) d += 'M' + (c + q) + ' ' + (r + q) + 'h1v1h-1z';
    var px = opts.size || 200;
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + px + '" height="' + px +
      '" viewBox="0 0 ' + size + ' ' + size + '" shape-rendering="crispEdges">' +
      '<rect width="' + size + '" height="' + size + '" fill="' + (opts.bg || '#fff') + '"/>' +
      '<path d="' + d + '" fill="' + (opts.fg || '#000') + '"/></svg>';
  }

  global.QR = { matrix: matrix, svg: svg };
})(window);

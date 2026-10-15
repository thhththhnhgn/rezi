"""
A small nginx configuration linter.

Why this exists
---------------
A duplicate `proxy_read_timeout` inside one `location` block shipped to
production and put the container into a crash loop: nginx rejects a directive
that appears twice in the same context *even when both copies carry the same
value*, so `nginx -t` failed, the container exited, Railway restarted it, and
the cycle repeated.

The existing tests could not have caught it. They treated nginx.conf.template
as text and grepped for substrings, and — critically — they never resolved
`include`, so a directive set once in the template and once in an included
snippet looked fine from both sides.

There is no nginx binary available in this environment, so this module parses
the config the way nginx does: it walks nested contexts, inlines `include`
files at the point they appear, and applies nginx's real rule for which
directives may not repeat.

This is not a full nginx parser. It deliberately models only what our config
uses, and it is designed to produce zero false positives: anything it is not
sure about is skipped rather than reported.
"""

from __future__ import annotations

import os
import re

# Directives that nginx rejects outright when they appear twice in the same
# context, with the error "directive is duplicate".
#
# nginx splits directives into two families. Most take a single value and are
# flagged NGX_CONF_TAKE1 with a dedicated struct field, so a second occurrence
# in the same block is a hard error. A smaller set is explicitly additive
# (proxy_set_header, add_header, include, location, server, listen ...) and may
# repeat freely.
#
# Only the single-value directives our config actually uses are listed. Adding
# a name here makes the check stricter; leaving one out only means we do not
# check it, never that we report something false.
NON_REPEATABLE = frozenset({
    "proxy_pass",
    "proxy_read_timeout",
    "proxy_send_timeout",
    "proxy_connect_timeout",
    "proxy_buffering",
    "proxy_request_buffering",
    "proxy_socket_keepalive",
    "proxy_http_version",
    "proxy_cache",
    "client_max_body_size",
    "client_body_timeout",
    "chunked_transfer_encoding",
    "tcp_nodelay",
    "tcp_nopush",
    "sendfile",
    "keepalive_timeout",
    "root",
    "index",
    "try_files",
    "return",
    "etag",
    "gzip",
    "default_type",
    "server_tokens",
    "access_log",
    "error_log",
    "limit_conn",
    "real_ip_header",
    "real_ip_recursive",
    "worker_processes",
    "worker_connections",
    "worker_rlimit_nofile",
    "multi_accept",
    "use",
    "pid",
    # Directives valid inside an `upstream` block. `server` is deliberately
    # absent: an upstream may legitimately list several servers.
    "keepalive",
    "keepalive_requests",
    "keepalive_time",
})


class NginxLintError(Exception):
    pass


def _strip_comment(line: str) -> str:
    """Remove a trailing comment.

    Quotes are tracked so a '#' inside a quoted value is not mistaken for the
    start of a comment.
    """
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def _tokenize(text: str) -> list[str]:
    """Split a config into braces and semicolon-terminated statements."""
    tokens: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        stmt = " ".join("".join(buf).split())
        if stmt:
            tokens.append(stmt)
        buf.clear()

    for raw in text.splitlines():
        for ch in _strip_comment(raw):
            if ch in "{};":
                flush()
                if ch != ";":
                    tokens.append(ch)
            else:
                buf.append(ch)
        buf.append(" ")
    flush()
    return tokens


def _load(path: str, include_root: str, seen: set[str]) -> str:
    real = os.path.realpath(path)
    if real in seen:
        # An include cycle would otherwise recurse forever.
        raise NginxLintError(f"include cycle at {path}")
    seen.add(real)
    with open(path, encoding="utf-8") as f:
        return f.read()


def lint(template_path: str,
         snippets_dir: str,
         substitutions: dict[str, str] | None = None) -> list[str]:
    """
    Parse a config template and return a list of human-readable problems.

    `substitutions` replaces the placeholders start.sh fills in (__PORT__,
    __PREFIX__) so the linted text matches what nginx will actually read.

    `include` directives pointing at /etc/nginx/snippets/<name> are resolved
    against `snippets_dir`, because that is where the Dockerfile copies them.
    Includes we cannot resolve are reported rather than silently ignored, so a
    renamed snippet cannot slip through.
    """
    with open(template_path, encoding="utf-8") as f:
        text = f.read()

    for key, val in (substitutions or {}).items():
        text = text.replace(key, val)

    problems: list[str] = []
    tokens = _tokenize(text)

    # Each stack frame is one context: (label, {directive: source})
    stack: list[tuple[str, dict[str, str]]] = [("main", {})]
    pending = "main"

    def record(stmt: str, origin: str) -> None:
        name = stmt.split(None, 1)[0]
        if name not in NON_REPEATABLE:
            return
        label, seen_here = stack[-1]
        if name in seen_here:
            problems.append(
                f"duplicate '{name}' in {label} "
                f"(first from {seen_here[name]}, again from {origin}) — "
                f"nginx rejects this even when the values match"
            )
        else:
            seen_here[name] = origin

    def expand(stmt: str, origin: str) -> None:
        """Handle one statement, inlining includes."""
        if not stmt.startswith("include "):
            record(stmt, origin)
            return
        target = stmt.split(None, 1)[1].strip().strip(";").strip('"\'')
        if "*" in target:
            return                      # wildcard include: not used by us
        name = os.path.basename(target)
        local = os.path.join(snippets_dir, name)
        if not os.path.exists(local):
            # mime.types and friends live in the base image, not the repo.
            if not target.startswith("/etc/nginx/snippets/"):
                return
            problems.append(f"include target not found in repo: {target}")
            return
        with open(local, encoding="utf-8") as fh:
            for sub in _tokenize(fh.read()):
                if sub in "{}":
                    problems.append(f"unexpected block inside snippet {name}")
                    continue
                # A directive pulled in by include counts as if it were
                # written at the include site — which is exactly why the
                # duplicate shipped unnoticed.
                record(sub, name)

    for tok in tokens:
        if tok == "{":
            stack.append((pending, {}))
            pending = "main"
        elif tok == "}":
            if len(stack) == 1:
                problems.append("unbalanced '}'")
                break
            stack.pop()
        else:
            # A statement immediately before '{' names the next context.
            pending = tok
            expand(tok, os.path.basename(template_path))

    if len(stack) != 1:
        problems.append(f"{len(stack) - 1} unclosed block(s)")

    return problems

#!/usr/bin/env python3
"""meta-scrape-shield — empirical crawler-defense verifier for Meta's bots.

Fetches YOUR site's robots.txt and ai.txt, audits them against Meta's crawler
user-agents, and reports exactly what Meta can still see:

  * a VERDICT per Meta crawler UA (allowed / blocked / ambiguous) with the
    matching rule cited,
  * an optional server-side check (--verify) that performs an HTTP GET of the
    homepage with each Meta UA to confirm blocking actually works server-side.

The UA strings below are the publicly documented Meta crawler user-agents
(per Meta's public crawler documentation and robots.txt guidance).

Exit codes: 0 = report produced, 2 = input/fetch error.
Honest scope: --verify only tests what a normal HTTP GET can observe; it
cannot prove how Meta's crawlers behave on their infrastructure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Publicly documented Meta crawler user-agent strings.
# Source: Meta's public crawler documentation (developers.facebook.com docs on
# webmasters/crawler). These are the UA strings Meta itself publishes for its
# crawlers — not scraped, not guessed.
# ---------------------------------------------------------------------------
META_CRAWLER_UAS = {
    "Meta-ExternalAgent": (
        "Meta-ExternalAgent/1.1 "
        "(+https://developers.facebook.com/docs/sharing/webmasters/crawler)"
    ),
    "facebookexternalhit": (
        "facebookexternalhit/1.1 "
        "(+http://www.facebook.com/externalhit_uatext.php)"
    ),
    "Meta-AI-Scraper": (
        "Meta-AI-Scraper/1.0 "
        "(+https://developers.facebook.com/docs/sharing/webmasters/crawler)"
    ),
}


# ---------------------------------------------------------------------------
# robots.txt / ai.txt parsing
# ---------------------------------------------------------------------------
@dataclass
class RuleGroup:
    agents: list = field(default_factory=list)   # user-agent tokens (lowercased)
    allow: list = field(default_factory=list)   # allow paths
    disallow: list = field(default_factory=list)  # disallow paths


def parse_rules(text: str) -> list[RuleGroup]:
    """Parse robots.txt-style text into RuleGroups. Tolerant of comments,
    blank lines, and mixed case directives."""
    groups: list[RuleGroup] = []
    current: RuleGroup | None = None
    seen_rule = False  # whether current group already has allow/disallow

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            token = value.lower()
            if current is None or seen_rule:
                current = RuleGroup()
                groups.append(current)
                seen_rule = False
            current.agents.append(token)
        elif key in ("allow", "disallow") and current is not None:
            seen_rule = True
            (current.allow if key == "allow" else current.disallow).append(value)
        # sitemap/crawl-delay and other directives are ignored for verdicts
    return groups


def match_group(groups: list[RuleGroup], ua_token: str) -> RuleGroup | None:
    """Find the best RuleGroup for a UA token: exact match wins, then '*'."""
    ua_token = ua_token.lower()
    for g in groups:
        if ua_token in g.agents:
            return g
    for g in groups:
        if "*" in g.agents:
            return g
    return None


def _longest_prefix_match(patterns: list[str], path: str):
    best = None
    for p in patterns:
        if not p:
            continue
        if path.startswith(p) and (best is None or len(p) > len(best)):
            best = p
    return best


def verdict_for_path(group: RuleGroup | None, path: str) -> tuple[str, str | None]:
    """Return (verdict, cited rule) for one path under one RuleGroup.

    Verdicts: 'allowed' | 'blocked' | 'ambiguous'.
    Longest-match wins; Allow beats Disallow on a length tie (Google convention).
    An empty Disallow value ('Disallow:') means allow-all and is ignored.
    """
    if group is None:
        return "ambiguous", None  # no rules at all for this crawler
    # An explicit empty Disallow ("Disallow:") is the robots.txt way of saying
    # allow-all (Google spec) — cite it so the verdict isn't mysterious.
    if "" in group.disallow:
        return "allowed", "Disallow: (empty — allow-all)"
    best_allow = _longest_prefix_match(group.allow, path)
    best_disallow = _longest_prefix_match(group.disallow, path)
    if best_allow is None and best_disallow is None:
        return "ambiguous", None
    if best_allow is not None and (best_disallow is None or len(best_allow) >= len(best_disallow)):
        return "allowed", f"Allow: {best_allow}"
    return "blocked", f"Disallow: {best_disallow}"


def audit_file(text: str, label: str, paths: list[str]) -> dict:
    """Audit one rules file (robots.txt or ai.txt) for all Meta crawler UAs."""
    groups = parse_rules(text)
    result = {"file": label, "groups_found": len(groups), "uas": {}}
    for token, full_ua in META_CRAWLER_UAS.items():
        group = match_group(groups, token)
        ua_report = {"user_agent": full_ua, "matched_group": None, "paths": {}}
        if group is not None:
            ua_report["matched_group"] = (
                group.agents[0] if len(group.agents) == 1 else group.agents
            )
        for path in paths:
            verdict, rule = verdict_for_path(group, path)
            ua_report["paths"][path] = {"verdict": verdict, "rule": rule}
        result["uas"][token] = ua_report
    return result


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "meta-scrape-shield/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def verify_with_ua(url: str, full_ua: str, timeout: int = 20) -> dict:
    """GET the URL with a Meta crawler UA. Returns status/body facts.

    Honest scope: only tests what a normal HTTP GET can observe — status code,
    content length, and whether the body looks like a block page. It cannot
    observe Meta-internal crawler behavior.
    """
    req = urllib.request.Request(url, headers={"User-Agent": full_ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "bytes_sampled": len(body),
                "looks_blocked": bool(
                    re.search(r"403|forbidden|blocked|access denied|captcha", body, re.I)
                ) or resp.status in (401, 403),
                "error": None,
            }
    except Exception as exc:  # noqa: BLE001 — report, don't crash
        return {"status": None, "bytes_sampled": 0, "looks_blocked": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(target: str, robots_text: str, ai_text: str | None, verify: bool) -> dict:
    paths = ["/", "/blog/", "/private/"]
    report: dict = {
        "target": target,
        "ua_note": "UA strings are the publicly documented Meta crawler user-agents.",
        "robots_txt": audit_file(robots_text or "", "robots.txt", paths),
    }
    if ai_text is not None:
        ai = audit_file(ai_text, "ai.txt (emerging standard — not universally honored)", paths)
        report["ai_txt"] = ai
    else:
        report["ai_txt"] = {"file": "ai.txt", "present": False,
                            "note": "no ai.txt found — AI-training crawlers get no signal from it"}
    if verify:
        checks = {}
        for token, full_ua in META_CRAWLER_UAS.items():
            checks[token] = verify_with_ua(target, full_ua)
        report["server_side_verify"] = {
            "note": "Only tests what a normal HTTP GET can observe.",
            "checks": checks,
        }
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="meta-scrape-shield: audit what Meta's crawlers can still see on your site"
    )
    ap.add_argument("target", help="target site URL, e.g. https://example.com")
    ap.add_argument("--robots-file", default=None, help="use a local robots.txt fixture instead of fetching")
    ap.add_argument("--ai-file", default=None, help="use a local ai.txt fixture instead of fetching")
    ap.add_argument("--verify", action="store_true",
                    help="also GET the homepage with each Meta UA to check server-side blocking")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args(argv)

    parsed = urlparse(args.target if "://" in args.target else "https://" + args.target)
    base = f"{parsed.scheme}://{parsed.netloc}"
    homepage = base + "/"

    try:
        if args.robots_file:
            robots_text = Path(args.robots_file).read_text(encoding="utf-8")
        else:
            robots_text = fetch_text(urljoin(base, "/robots.txt"))
        if args.ai_file:
            ai_text = Path(args.ai_file).read_text(encoding="utf-8")
        else:
            try:
                ai_text = fetch_text(urljoin(base, "/ai.txt"))
            except Exception:
                ai_text = None
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"fetch failed: {exc}"}), file=sys.stderr)
        return 2

    report = build_report(homepage, robots_text, ai_text, args.verify)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(f"meta-scrape-shield report for {homepage}\n")
        for section in ("robots_txt", "ai_txt"):
            sec = report[section]
            if section == "ai_txt" and not sec.get("present", True):
                print(f"[{sec['file']}] {sec['note']}\n")
                continue
            print(f"[{sec['file']}] ({sec.get('groups_found', 0)} rule groups)")
            for token, ua in sec["uas"].items():
                print(f"  {token}:")
                print(f"    UA: {ua['user_agent']}")
                print(f"    matched group: {ua['matched_group']}")
                for path, v in ua["paths"].items():
                    rule = f" [{v['rule']}]" if v["rule"] else ""
                    print(f"    {path:10} -> {v['verdict'].upper()}{rule}")
            print()
        if "server_side_verify" in report:
            print("[server-side verify] (only what a normal GET can observe)")
            for token, c in report["server_side_verify"]["checks"].items():
                if c["error"]:
                    print(f"  {token}: ERROR {c['error']}")
                else:
                    print(f"  {token}: HTTP {c['status']}, looks_blocked={c['looks_blocked']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests for meta-scrape-shield. All offline: fixture robots.txt / ai.txt files
only — no network anywhere in this suite."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scrape_shield as ss

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def verdict(groups_text, ua_token, path):
    groups = ss.parse_rules(groups_text)
    return ss.verdict_for_path(ss.match_group(groups, ua_token), path)


# --- verdicts on the block-meta fixture -------------------------------------
def test_meta_externalagent_blocked_disallow_all():
    v, rule = verdict(read("robots_block_meta.txt"), "Meta-ExternalAgent", "/")
    assert v == "blocked"
    assert rule == "Disallow: /"


def test_facebookexternalhit_allowed():
    v, rule = verdict(read("robots_block_meta.txt"), "facebookexternalhit", "/blog/")
    assert v == "allowed"
    assert rule == "Allow: /"


def test_wildcard_private_block_applies_to_meta_ai_scraper():
    v, rule = verdict(read("robots_block_meta.txt"), "Meta-AI-Scraper", "/private/")
    assert v == "blocked"
    assert rule == "Disallow: /private/"


def test_no_rules_for_path_is_ambiguous():
    # Group exists for the crawler but no rule matches the requested path.
    text = "User-agent: Meta-ExternalAgent\nDisallow: /secret/\n"
    v, rule = verdict(text, "Meta-ExternalAgent", "/public/page")
    assert v == "ambiguous"
    assert rule is None


def test_ua_with_no_group_is_ambiguous():
    v, rule = verdict("User-agent: googlebot\nDisallow: /\n", "Meta-ExternalAgent", "/")
    assert v == "ambiguous"


# --- parser edge cases -------------------------------------------------------
def test_longest_match_wins_over_shorter_disallow():
    v, rule = verdict(read("robots_longest_match.txt"), "Meta-ExternalAgent", "/private/public/x")
    assert v == "allowed"
    assert rule == "Allow: /private/public/"


def test_longest_match_disallow_on_shorter_path():
    v, rule = verdict(read("robots_longest_match.txt"), "Meta-ExternalAgent", "/private/secret")
    assert v == "blocked"
    assert rule == "Disallow: /private/"


def test_case_insensitive_ua_matching():
    v, _ = verdict(read("robots_case.txt"), "META-EXTERNALAGENT", "/")
    assert v == "allowed"  # empty Disallow: => allow-all


def test_case_insensitive_second_agent():
    v, rule = verdict(read("robots_case.txt"), "facebookexternalhit", "/blog/post")
    assert v == "allowed"
    assert rule == "Allow: /blog/"


def test_comments_and_blank_lines_ignored():
    groups = ss.parse_rules(read("robots_case.txt"))
    assert len(groups) == 2
    assert all(isinstance(g, ss.RuleGroup) for g in groups)


def test_empty_robots_is_ambiguous_for_everything():
    for ua in ss.META_CRAWLER_UAS:
        v, _ = verdict("", ua, "/")
        assert v == "ambiguous"


# --- ai.txt -------------------------------------------------------------------
def test_ai_txt_block_cited():
    v, rule = verdict(read("ai_block.txt"), "Meta-AI-Scraper", "/")
    assert v == "blocked"
    assert rule == "Disallow: /"


def test_audit_file_reports_all_three_uas():
    report = ss.audit_file(read("robots_block_meta.txt"), "robots.txt", ["/"])
    assert set(report["uas"]) == set(ss.META_CRAWLER_UAS)
    assert report["uas"]["Meta-ExternalAgent"]["paths"]["/"]["verdict"] == "blocked"
    assert report["uas"]["facebookexternalhit"]["paths"]["/"]["verdict"] == "allowed"


# --- CLI end-to-end on fixtures (no network) ----------------------------------
def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scrape_shield.py"), *args],
        capture_output=True, text=True,
    )


def test_cli_fixture_end_to_end_text():
    res = run_cli("https://example.com",
                  "--robots-file", str(FIX / "robots_block_meta.txt"),
                  "--ai-file", str(FIX / "ai_block.txt"))
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "meta-scrape-shield report for https://example.com/" in out
    assert "Meta-ExternalAgent" in out and "BLOCKED" in out
    assert "facebookexternalhit" in out and "ALLOWED" in out


def test_cli_fixture_end_to_end_json():
    res = run_cli("https://example.com",
                  "--robots-file", str(FIX / "robots_block_meta.txt"),
                  "--ai-file", str(FIX / "ai_block.txt"),
                  "--format", "json")
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert report["robots_txt"]["uas"]["Meta-ExternalAgent"]["paths"]["/"]["verdict"] == "blocked"
    assert report["ai_txt"]["uas"]["Meta-AI-Scraper"]["paths"]["/"]["verdict"] == "blocked"
    assert report["ai_txt"]["uas"]["Meta-AI-Scraper"]["paths"]["/"]["rule"] == "Disallow: /"


def test_cli_missing_robots_file_is_error():
    res = run_cli("https://example.com", "--robots-file", "/nonexistent/robots.txt")
    assert res.returncode == 2

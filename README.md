# meta-scrape-shield

Empirical crawler-defense verifier. Audits **your** site's `robots.txt` and `ai.txt` against Meta's crawler user-agents and reports exactly what Meta can still see — one VERDICT per crawler (`allowed` / `blocked` / `ambiguous`) with the matching rule cited. An optional `--verify` mode performs an HTTP GET of your homepage with each Meta UA to confirm server-side blocking actually works.

The user-agent strings used are the **publicly documented Meta crawler UAs** (per Meta's public crawler documentation): `Meta-ExternalAgent`, `facebookexternalhit`, and `Meta-AI-Scraper`.

## The news hook (2026-10-16 → 2026-10-17)

Meta's updated commercial terms (effective Oct 30, 2026) briefly let it scrape sites "associated with" business accounts to train AI — overriding robots.txt. After backlash, Meta removed the provision on Oct 17.

Source: [TechCrunch — Meta removes language that raised scraping and AI-training concerns](https://techcrunch.com/2026/10/17/meta-removes-language-that-raised-scraping-and-ai-training-concerns/)

The provision is gone, but the lesson stands: **robots.txt is a voluntary signal, and site owners have no empirical way to check what Meta's crawlers actually honor.** This tool gives them that check.

## How to run

No dependencies beyond Python 3.12.

```bash
# Audit a live site (fetches /robots.txt and /ai.txt)
python3 scrape_shield.py https://yoursite.com

# ...and verify server-side blocking actually works with real GETs
python3 scrape_shield.py https://yoursite.com --verify

# Machine-readable output
python3 scrape_shield.py https://yoursite.com --format json

# Offline, against local fixtures (what the test suite uses)
python3 scrape_shield.py https://example.com \
  --robots-file tests/fixtures/robots_block_meta.txt \
  --ai-file tests/fixtures/ai_block.txt

# Full test suite (offline — no network)
python3 -m pytest -v
```

Example output:

```
[robots.txt] (3 rule groups)
  Meta-ExternalAgent:
    matched group: meta-externalagent
    /          -> BLOCKED [Disallow: /]
    /blog/     -> BLOCKED [Disallow: /]
    /private/  -> BLOCKED [Disallow: /]
```

Verdict semantics: longest-match rule wins (Allow beats Disallow on ties, per Google convention); `Disallow:` with no value means allow-all and is cited as such; a crawler with no matching group or no matching rule is `ambiguous`, not silently allowed.

## What it does NOT do

- `--verify` only tests what a normal HTTP GET can observe (status code, body hints). It cannot prove how Meta's crawlers behave on Meta's infrastructure.
- It cannot detect scraping that ignores robots.txt entirely — no client-side tool can.
- `ai.txt` is an emerging, non-universal standard; a verdict there is advisory.
- It does not modify your robots.txt or block anything — it is a verifier, not a firewall.

## Built by Ingenious AI

Part of the [Ingenious AI](https://github.com/Iceman2050) security tooling suite:

[DisclosureGuard](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20DisclosureGuard.)
[ModelMinder](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20ModelMinder.)
[TermsWatch](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20TermsWatch.)
[Vibe-Code Audit](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20Vibe-Code%20Audit.)
[Rogue-Agent Defense](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20Rogue-Agent%20Defense.)
[BreachHunter](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20BreachHunter.)
[ChatBreaker](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20ChatBreaker.)
[Agent Flight Recorder](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20Agent%20Flight%20Recorder.)
[Agent Auth Gateway](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20Agent%20Auth%20Gateway.)
[DomainGuard](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20DomainGuard.)
[ContentCraft AI](https://wa.me/5016691053?text=Hi%20Ingenious%20AI!%20I%20want%20early%20access%20to%20ContentCraft%20AI.)

## License

MIT — see [LICENSE](LICENSE).

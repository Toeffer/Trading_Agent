# OpenClaw Crypto Trading Agent

Skill-based crypto trading agent. Runs 24/7 on a VPS (or Pi). Strategy and risk rules
are in [CLAUDE.md](CLAUDE.md) — read that first.

## Quick start (server)

```bash
# 1. Clone
git clone git@github.com:<your-username>/Trading_Agent.git
cd Trading_Agent

# 2. Generate config files from templates
make setup

# 3. Edit .env — fill in API keys, Telegram bot, LLM key
vim .env

# 4. Record the SAE config hash baseline
make sae-hash

# 5. Build the container
make build

# 6. Preflight — verifies all credentials work BEFORE any trade
make preflight

# 7. Start
make up

# 8. Watch
make logs
```

Telegram should receive a "Trading Agent: preflight check OK" message during step 6,
and a startup notification during step 7. If you don't see either, the bot is misconfigured.

## Layout

```
.
├── CLAUDE.md                  # Authoritative behavior spec — read this first
├── SETUP.md                   # Full operator checklist (hardware, accounts, keys)
├── Makefile                   # `make help` for all commands
├── docker-compose.yml         # Service definition (bridge net, read-only fs, no caps)
├── Dockerfile                 # Python 3.11-slim base
├── requirements.txt           # Python deps (ccxt, openai SDK, telegram, pytest)
├── .env.example               # Copy → .env, fill in secrets
├── config/
│   ├── sae-config.yaml        # Hard safety rules (committed; hash-checked)
│   ├── exchanges.yaml.example # Copy → exchanges.yaml (gitignored)
│   └── openclaw.json.example  # Copy → openclaw.json (gitignored)
├── scripts/
│   ├── preflight.py           # Credential + API + Telegram check
│   ├── backup.sh              # Encrypted weekly backup (cron)
│   └── sae-hash.sh            # SAE config integrity
└── tests/
    ├── test_sae_config.py     # Invariants from CLAUDE.md §6
    └── test_position_sizing.py # Formula from CLAUDE.md §5.7
```

## Daily commands

| Command | What it does |
|---|---|
| `make logs` | Tail agent output |
| `make ps` | Show container status |
| `make restart` | Restart the agent |
| `make test` | Run unit tests |
| `make backup` | Manual encrypted backup |
| `make sae-hash-verify` | Confirm SAE rules haven't been tampered with |

## What this scaffold gives you vs. what you still need

**Ready to use:**
- Config templates that map 1:1 to CLAUDE.md §4 / §6 / §7
- Preflight script that catches the most common setup mistakes before you spend money
- Tests that fail if anyone edits SAE rules incorrectly
- Hardened Docker setup (read-only root, no capabilities, bridge net only)
- SAE hash integrity per CLAUDE.md §11 rule 10

**Still TODO before live trading** — see `SETUP.md` for the full list. Highlights:
- OpenClaw install line in `Dockerfile` (the actual install command depends on
  how OpenClaw is distributed — left as a TODO)
- Exchange-specific minimum lot sizes for assets you trade beyond BTC/ETH
- Real Telegram chat ID + bot token + LLM provider key
- Backups copied **off-host** (`backup.sh` writes locally; you wire up rsync/S3/etc.)
- Cron entry for weekly backup
- Decide whether stops rest on the exchange (recommended) or in-agent —
  CLAUDE.md is silent; SETUP.md flags this as an operator decision

## Safety reminders

- The withdraw permission on all exchange API keys must be **disabled**, not just unused
- Every short trade requires manual operator confirmation via Telegram — autopilot
  is permanently disabled for Strategy D
- Daily loss > 4% = kill switch fires automatically. You must manually re-enable.
- Read all 16 "NOT allowed to do" items in CLAUDE.md §15 before deploying

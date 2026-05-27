# SETUP — Operator Pre-flight Checklist

Run through every section before `make up`. Skipping items risks losing real money.

This document is **operator-facing** — actions YOU need to take outside the repo.
Inside-the-repo configuration is in [README.md](README.md).

---

## 1. VPS / host

- [ ] x86_64 Linux VPS provisioned (4+ GB RAM, 30+ GB disk, stable Ethernet)
- [ ] OS up to date (`apt update && apt upgrade -y`)
- [ ] Time zone set to UTC (`timedatectl set-timezone UTC`)
- [ ] NTP enabled (`timedatectl set-ntp true`) — 4H candle timing depends on this
- [ ] Docker + Docker Compose installed (`docker --version` and `docker compose version`)
- [ ] Non-root user with docker group membership (don't run the agent as root)
- [ ] SSH key-only login; password auth disabled in `/etc/ssh/sshd_config`
- [ ] UFW (or equivalent firewall) — outbound HTTPS allowed, no unnecessary inbound ports
- [ ] Automatic security updates configured (`unattended-upgrades` on Debian/Ubuntu)
- [ ] (Optional but recommended) UPS or VPS provider with battery backup —
      a power loss between trailing-stop updates leaves the last-placed exchange
      stop active at a stale level

---

## 2. Exchange accounts

### Binance
- [ ] KYC complete
- [ ] USD-M Perpetual Futures enabled in account settings
- [ ] API key generated with permissions: **Enable Reading**, **Enable Spot & Margin Trading**, **Enable Futures**
- [ ] Withdraw permission **NOT** ticked
- [ ] IP allowlist configured — locked to the VPS public IP only
- [ ] Initial capital deposited in USDT
- [ ] Confirm STOP-MARKET orders work on your account tier (place a tiny test trade with one)

### KuCoin
- [ ] KYC complete
- [ ] API key generated: **General**, **Trade** (no Transfer, no Withdraw)
- [ ] API passphrase noted
- [ ] IP allowlist locked to VPS IP

### Binance Testnet
- [ ] Testnet account created at <https://testnet.binance.vision/>
- [ ] Testnet API key + secret saved (separate from production)
- [ ] Testnet has play balance for paper trading

---

## 3. LLM provider

Per CLAUDE.md §7: DeepSeek V4 Flash + Pro via OpenRouter (recommended).

- [ ] OpenRouter account at <https://openrouter.ai>
- [ ] Credit added (~$5 is enough for several months at the documented volume)
- [ ] Spending limit set on the account (so a runaway loop can't drain you)
- [ ] API key generated → `OPENROUTER_API_KEY`

Or, if going direct:
- [ ] DeepSeek account + API key → `DEEPSEEK_API_KEY`

> Note: the **exact model slugs** for `deepseek/deepseek-v4-flash` and
> `deepseek/deepseek-v4-pro` on each provider may differ from CLAUDE.md §7.
> Verify the actual slug in your provider's model catalog before preflight runs.
> The preflight script has `TODO(operator)` markers where slugs are referenced.

---

## 4. Telegram

- [ ] Bot created via [@BotFather](https://t.me/BotFather) → token saved
- [ ] Operator's chat ID obtained (message [@userinfobot](https://t.me/userinfobot)) → numeric chat ID saved
- [ ] You sent at least one message to your bot (Telegram won't let bots message
      you until you initiate the chat first)
- [ ] Bot token → `TELEGRAM_BOT_TOKEN`
- [ ] Chat ID → `TELEGRAM_CHAT_ID`

Test outside the agent:
```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="manual setup test"
```
You should receive the message in your Telegram chat. If not, fix this before continuing.

---

## 5. .env file

- [ ] `make setup` ran successfully — creates `.env`, `config/exchanges.yaml`, `config/openclaw.json`
- [ ] `.env` filled in with all real values
- [ ] `BACKUP_PASSPHRASE` set to a strong, randomly-generated value (stored
      separately — e.g. in a password manager — because you'll need it to
      decrypt backups during recovery)
- [ ] `.env` permissions: `chmod 600 .env`
- [ ] `.env` not tracked by git: `git status` should NOT show it

---

## 6. SAE config integrity

- [ ] `make sae-hash` ran successfully → `.sae-config.hash` exists
- [ ] `.sae-config.hash` committed alongside `config/sae-config.yaml`
- [ ] Whenever you edit `config/sae-config.yaml` intentionally, re-run `make sae-hash`
      and commit BOTH files together

The hash check fires every preflight and at session start. If it mismatches
unexpectedly, halt and investigate — someone changed your safety rules.

---

## 7. Preflight & first run

- [ ] `make preflight` returns OK on every check
- [ ] Telegram received the "preflight check OK" message
- [ ] `make up` starts the container without errors
- [ ] `make logs` shows the agent starting clean
- [ ] Telegram received the startup notification

---

## 8. Open decisions the operator must make BEFORE live trading

These are NOT in CLAUDE.md but matter operationally:

### 8.1 Where do stops actually rest?
CLAUDE.md describes computing stops every 4H candle close, but doesn't say
whether they live as resting orders on the exchange or only in agent memory.

**Recommended:** Hard stops (Phase 1) as resting STOP-MARKET orders on the exchange,
trailing stops cancel-and-replace on each candle. This way agent downtime ≠ no
protection. Decide and document in your own ops notes.

### 8.2 Where do encrypted backups go off-host?
`scripts/backup.sh` writes encrypted blobs to `./backups/` locally. You must
add an off-host copy step. Common options:
- `rsync -av ./backups/ user@backup-host:/srv/trading-backups/`
- `aws s3 cp ./backups/ s3://your-bucket/trading-backups/ --recursive`
- Mounted external storage (`cp ./backups/*.gpg /mnt/external/`)

The TODO marker in `scripts/backup.sh` shows where to add this.

### 8.3 Cron entry for weekly backup
```cron
# Sunday 03:00 UTC — encrypted weekly backup
0 3 * * 0 cd /opt/trading-agent && ./scripts/backup.sh >> backups/backup.log 2>&1
```

### 8.4 OpenClaw install
The Dockerfile has `TODO(operator)` lines for OpenClaw's install command and
entrypoint. Fill these in once you know how OpenClaw is distributed
(pip package? git repo? release binary?).

---

## 9. Pre-go-live gates (from CLAUDE.md §12 + §13)

Do not enable live trading until ALL of the following are true:

- [ ] Strategy A (grid): 14 days paper trading on testnet, autopilot OFF until then
- [ ] Strategy B (trend follow): 7 days paper + first 10 trades manually confirmed
- [ ] Strategy C (funding harvest): 7 days paper, autopilot stays OFF permanently
- [ ] Strategy D (speculative short): blocked for 60 days minimum after A–C are live
- [ ] Backtester meets acceptance thresholds for each strategy (Sharpe ≥ 1.0,
      DD ≤ 8%, win-rate per CLAUDE.md §12 step 4)
- [ ] You have read all 16 forbidden actions in CLAUDE.md §15
- [ ] You can recite the four kill-switch phrases without looking them up
- [ ] You know how to revoke an exchange API key from a phone if you're away from the VPS

---

## 10. After go-live — recurring operator tasks

| Cadence | Task |
|---|---|
| Daily | Read the 08:00 UTC Telegram P&L digest |
| Weekly | Read Monday 08:00 P&L summary; review regime classifier accuracy |
| Weekly | Verify `make backup` ran and was copied off-host |
| Monthly | Review LLM spend (target: under $3/month per CLAUDE.md §7) |
| Quarterly | Rotate all exchange + LLM + Telegram API keys |
| Quarterly | `apt update && apt upgrade && make build && make restart` |

# docs/openclaw — Werner (OpenClaw) runtime files

| Path | What |
|---|---|
| `../../CLAUDE.md` (repository root) | **Werner's instructions — the only current copy.** |
| `archive/CLAUDE.pre-refactor.md` | Pre-2026-06-09 monolithic instructions. History only; its FX sizing rule is wrong. |
| `memory/` | Snapshots of host memory files (routing policy, Phase 2F monitoring runbook). |

## Deployment

The live Werner reads `~/.openclaw/CLAUDE.md` on the host, a separate file from
the repository checkout at `~/agents/ibkr-bridge/CLAUDE.md`. Keep them identical
by making the deployed file a symlink to the checkout:

```bash
mv ~/.openclaw/CLAUDE.md ~/.openclaw/CLAUDE.md.bak-$(date +%Y%m%d)   # keep the old one
ln -s ~/agents/ibkr-bridge/CLAUDE.md ~/.openclaw/CLAUDE.md
```

`ibkr-operator doctor` check `werner_instructions_current` fails whenever the
deployed file differs from the checkout, and names known-stale rules it finds
(for example the old `fx_rate = ibkr_account.ExchangeRate` sizing rule).

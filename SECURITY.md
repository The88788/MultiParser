# Security policy

This is an unfinished open-source project, with no guaranteed security support or active maintenance schedule.

## What must stay local

- `.env`, `config_wb.json`, `config_ozon.json`, `config.json`
- `profiles/`, browser cookies, session state, `proxies/`, `logs/`, `output/`
- Any API keys for CAPTCHA services, Telegram bot tokens, proxy credentials, user data and session tokens

The app currently stores secrets in plaintext in local files when entered via the GUI. The optional `.env` support reduces the need to manually edit JSON but **does not encrypt credentials**. GUI saving may copy effective values into the ignored JSON config.

## Disclosure

Do not open public issues or PRs containing working secrets. Report vulnerabilities privately to the repository owner via GitHub. If a key was ever committed, **revoke/rotate it**: deleting a file from the latest commit is not sufficient, because earlier Git history and forks may retain it.

Prior to making the repository public, run a full Git history secret scan with a tool such as Gitleaks or TruffleHog, audit the results and rotate all exposed credentials. Review historical committed local config files and documentation. Rewriting history, if needed, requires a separate coordinated process and force-push; this preparation PR intentionally does not rewrite history.

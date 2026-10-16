# MultiParser: Windows data parser toolkit

**MultiParser** is an open-source Python desktop project with a Windows GUI for collecting product data from **Wildberries** and **Ozon**. It is also a starting point for building other custom web/data parsers.

> **Project status: functional foundation, unfinished release.** The original commissioned development stopped before final packaging and polishing. The code and GUI exist, but there are unfinished parts, no verified release builds, and scraping may need adaptation to current websites. This is **not** a ready-to-install, production-guaranteed application.

**Русский:** проект можно бесплатно использовать и развивать на условиях MIT. Приложение создавалось для практических задач, но работа над заказом была прекращена до финальной сборки. Интерфейс Windows и основная архитектура готовы. Функциональность отдельных модулей требует тестирования и актуализации. Pull requests приветствуются!

## Features / Возможности

- Two Windows GUI entry points: WB and Ozon (PySide6 / Qt).
- Browser-driven collection (Playwright and additional browser strategies).
- Product data parsing and Excel export.
- Multiple parsing jobs, queue, concurrency settings.
- Proxy management and proxy health checks.
- Optional CAPTCHA service integrations: 2Captcha, CapSolver, Anti-Captcha.
- Scheduling / recurring jobs, logs and progress.
- Optional Telegram notifications.
- Modular core, parsers and GUI folders: adaptable for other data sources.

These are **implemented components**, not a promise that every mode works on today's third-party websites.

## Screenshots / Интерфейс

Real project screenshots from the developer's portfolio:

- [Wildberries Parser: GUI, settings and scheduler](https://www.fl.ru/user/grayzor/portfolio/8055749/)
- [Ozon Parser: GUI and parsing options](https://www.fl.ru/user/grayzor/portfolio/8055761/)

Screenshots are linked to their source instead of embedding unverified copied media.

## Quick start (Windows)

See **[INSTALL.md](INSTALL.md)** for full instructions and troubleshooting.

```powershell
git clone https://github.com/The88788/MultiParser.git
cd MultiParser
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe main_wb.py
```

For Ozon use `main_ozon.py`. Python 3.12 is a suggested compatibility starting point, **not a tested guarantee**.

On first launch each app copies its `config_*.default.json` to an ignored local `config_*.json`; edit settings in the GUI. Optional secret values can also be read from the ignored `.env` (copy `.env.example`). **Never publish your filled configuration, cookies or proxies.**

## Structure

```text
core/                 Scheduling, proxy management, shared utilities
gui/wb/               Wildberries Windows UI
gui/ozon/             Ozon Windows UI
parsers/wb/           Wildberries parsing/extraction/export
parsers/ozon/         Ozon parsing/extraction/export
assets/               Icons and UI assets
main_wb.py            WB entry point
main_ozon.py          Ozon entry point
main_wb.spec          Experimental PyInstaller spec
main_ozon.spec        Experimental PyInstaller spec
config_*.default.json Safe defaults (without personal keys)
.env.example          Optional environment variables template
```

## Development status and roadmap

Potential contributions: Windows smoke tests, dependency/version compatibility, reliable EXE packaging, parsing selectors and CAPTCHA workflow updates, better error handling and diagnostics, automated tests, refactoring shared code, documentation and examples for extending to other sites.

No EXE release has been validated or published. `*.spec` files are **experimental build configurations**, not proof that packaging works. Use at your own risk and follow the terms and rate limits of target services.

## Contributions & paid custom work

- **Free**: clone, use, fork, modify and redistribute under the MIT License.
- **Open source**: bug reports, fixes and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
- **Custom development**: need a new parser, features, an integration or a finished Windows build based on this codebase? Paid custom development is available.

**Developer:** [The 88788](https://www.the88788.com/) · [GitHub @The88788](https://github.com/The88788)

## Security and license

Do not commit real credentials, session cookies or private data. See [SECURITY.md](SECURITY.md).

MIT License: [LICENSE](LICENSE). The project is independent and is not affiliated with Wildberries or Ozon.

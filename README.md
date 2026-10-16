# MultiParser: Open Source Windows Parsing Platform

**MultiParser** is a functional open-source Windows desktop data-collection application written in Python, with dedicated graphical interfaces for **Wildberries** and **Ozon**. Its modular architecture also provides a starting point for building custom parsers for other data sources.

> **Status: working application, community-maintained development welcome.** The original commissioned project was stopped before final polishing and Windows packaging. The desktop UI and core parsing workflows were developed as working software, not merely UI mockups. Because marketplace websites change, selectors and browser/challenge handling may need updating before a new deployment. There is **no tested Windows EXE release** yet.

**Русский:** MultiParser представляет собой **рабочий проект парсера данных под Windows**, а не просто прототип интерфейса. В нём реализованы GUI, сбор данных Wildberries и Ozon, обработка списков ID, прокси, антикапча, автоматизация и экспорт в Excel. Разработка для заказчика прекратилась до окончательной доработки и сборки EXE. Для возобновления эксплуатации может потребоваться обновить селекторы сайтов и проверить актуальные механизмы защиты. Проект доступен бесплатно по лицензии MIT; предложения, Issues и Pull Requests приветствуются!

## Features / Возможности

- Two Windows GUI entry points: WB and Ozon (PySide6 / Qt).
- Browser-driven collection (Playwright and additional browser strategies).
- Product data parsing and Excel export.
- Product-ID lists, job queues, multi-job runs and concurrency settings.
- Proxy management and proxy health checks.
- Optional CAPTCHA service integrations: 2Captcha, CapSolver, Anti-Captcha.
- Scheduling / recurring jobs, logs and progress.
- Optional Telegram notifications.
- Modular core, parsers and GUI folders: adaptable for other data sources.

### Bulk collection / Массовый сбор

The architecture is designed for **bulk collection of thousands of product IDs** with a managed pool of proxies and configurable concurrency. A pool of approximately **30–50 proxies** was identified by the developer as a practical deployment scenario, not a minimum requirement or a verified performance benchmark. Actual throughput and reliability depend on proxy quality, active site protections, selectors, machine resources and configuration.

**Масштабирование:** система рассчитана на массовый сбор данных по спискам в несколько тысяч ID. Для практической эксплуатации можно использовать пул ориентировочно из **30–50 прокси**, но это сценарий настройки, а не гарантия скорости или отсутствия блокировок.

The listed capabilities are implemented in source code. Compatibility with *current* site versions and all combinations of settings has not been revalidated for this open-source release.

## Screenshots / Интерфейс

Оригинальные скриншоты Windows-приложений WB Parser и Ozon Parser будут добавлены непосредственно в репозиторий в `docs/screenshots/` после удаления персональных данных, API-ключей и реквизитов прокси.

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

The main open tasks are refreshing selectors and browser/challenge logic as marketplace pages evolve, checking dependency compatibility, completing a reliable Windows EXE build, improving diagnostics and tests, and documenting how to adapt the architecture for additional sources.

**The application is usable from Python source, subject to dependency and website compatibility.** The absence of a published EXE does not mean the desktop interface or underlying parser was only a mockup.

No EXE release has been validated or published. `*.spec` files are **experimental build configurations**, not proof that packaging works. Use at your own risk and follow the terms and rate limits of target services.

## Contributions & paid custom work

- **Free**: clone, use, fork, modify and redistribute under the MIT License.
- **Open source**: bug reports, fixes and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
- **Custom development**: need a new parser, features, an integration or a finished Windows build based on this codebase? Paid custom development is available.

**Developer:** [The 88788](https://www.the88788.com/) · [GitHub @The88788](https://github.com/The88788)

## Security and license

Do not commit real credentials, session cookies or private data. See [SECURITY.md](SECURITY.md).

MIT License: [LICENSE](LICENSE). The project is independent and is not affiliated with Wildberries or Ozon.

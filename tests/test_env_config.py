import tempfile
import unittest
from pathlib import Path

from core.env_config import read_dotenv, apply_env_overrides


class EnvConfigTests(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(read_dotenv(Path("this-file-should-not-exist.env")), {})

    def test_wb_overrides_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text(
                "MULTIPARSER_WB_CAPSOLVER_API_KEY=wb-secret\n"
                "MULTIPARSER_OZON_CAPSOLVER_API_KEY=ozon-secret\n",
                encoding="utf-8",
            )
            cfg = {"captcha": {"capsolver_api_key": ""}}
            apply_env_overrides(cfg, "WB", p, environ={})
            self.assertEqual(cfg["captcha"]["capsolver_api_key"], "wb-secret")

    def test_process_environment_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text("MULTIPARSER_WB_TELEGRAM_CHAT_ID=from-file\n", encoding="utf-8")
            cfg = {"notifications": {"chat_id": ""}}
            apply_env_overrides(cfg, "WB", p, environ={"MULTIPARSER_WB_TELEGRAM_CHAT_ID": "from-process"})
            self.assertEqual(cfg["notifications"]["chat_id"], "from-process")

    def test_empty_values_do_not_erase_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text("MULTIPARSER_OZON_2CAPTCHA_API_KEY=\n", encoding="utf-8")
            cfg = {"captcha": {"twocaptcha_api_key": "from-gui"}}
            apply_env_overrides(cfg, "OZON", p, environ={})
            self.assertEqual(cfg["captcha"]["twocaptcha_api_key"], "from-gui")


if __name__ == "__main__":
    unittest.main()

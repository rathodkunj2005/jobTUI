"""Configuration management — reads config.ini then falls back to env vars."""
import configparser
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.ini"


def load() -> dict:
    cfg = {
        # Candidate
        "name": "Kunj Rathod",
        "email": "",
        "phone": "",
        "linkedin": "",
        "github": "",
        # SMTP (for reminders)
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "notify_to": "",
        "notify_from": "",
    }

    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE)
        if "candidate" in parser:
            for k, v in parser["candidate"].items():
                if k in cfg:
                    cfg[k] = v
        if "smtp" in parser:
            for k, v in parser["smtp"].items():
                key = f"smtp_{k}" if not k.startswith("smtp_") else k
                if key in cfg:
                    cfg[key] = v
            if "to" in parser["smtp"]:
                cfg["notify_to"] = parser["smtp"]["to"]
            if "from" in parser["smtp"]:
                cfg["notify_from"] = parser["smtp"]["from"]

    # Env var overrides (TRACKER_<KEY> pattern)
    env_map = {
        "TRACKER_EMAIL": "email",
        "TRACKER_PHONE": "phone",
        "TRACKER_LINKEDIN": "linkedin",
        "TRACKER_GITHUB": "github",
        "TRACKER_SMTP_HOST": "smtp_host",
        "TRACKER_SMTP_PORT": "smtp_port",
        "TRACKER_SMTP_USER": "smtp_user",
        "TRACKER_SMTP_PASS": "smtp_pass",
        "TRACKER_NOTIFY_TO": "notify_to",
        "TRACKER_NOTIFY_FROM": "notify_from",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val

    return cfg

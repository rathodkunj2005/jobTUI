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
        # Resume generation
        "resume_provider": "auto",  # auto | anthropic | openai | codex_cli | claude_cli
        "resume_model": "",
        "resume_api_key": "",  # backwards-compatible alias for Anthropic
        "resume_anthropic_api_key": "",
        "resume_openai_api_key": "",
        "resume_templates_dir": "",
        "resume_output_dir": "",
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
        if "resume" in parser:
            sec = parser["resume"]
            if "provider" in sec:
                cfg["resume_provider"] = sec["provider"]
            if "model" in sec:
                cfg["resume_model"] = sec["model"]
            if "anthropic_api_key" in sec:
                cfg["resume_api_key"] = sec["anthropic_api_key"]
                cfg["resume_anthropic_api_key"] = sec["anthropic_api_key"]
            if "openai_api_key" in sec:
                cfg["resume_openai_api_key"] = sec["openai_api_key"]
            if "templates_dir" in sec:
                cfg["resume_templates_dir"] = sec["templates_dir"]
            if "output_dir" in sec:
                cfg["resume_output_dir"] = sec["output_dir"]

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
        "ANTHROPIC_API_KEY": "resume_anthropic_api_key",
        "OPENAI_API_KEY": "resume_openai_api_key",
        "TRACKER_RESUME_PROVIDER": "resume_provider",
        "TRACKER_RESUME_MODEL": "resume_model",
        "TRACKER_RESUME_TEMPLATES_DIR": "resume_templates_dir",
        "TRACKER_RESUME_OUTPUT_DIR": "resume_output_dir",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
            if cfg_key == "resume_anthropic_api_key":
                cfg["resume_api_key"] = val

    return cfg

"""Read config.toml once and resolve paths against the repo root."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.toml"
VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _require(table, key, where, source):
    try:
        return table[key]
    except KeyError:
        raise ConfigError(f"{source}: missing key '{key}' in [{where}]") from None


class Config:
    """Resolved configuration. Paths are absolute by the time anything reads them."""

    def __init__(self, data, source):
        self.source = source
        paths = _require(data, "paths", "top level", source)
        self.db_path = self._resolve(_require(paths, "db", "paths", source))
        self.raw_dir = self._resolve(paths.get("raw_dir", "data/raw"))
        level = str(data.get("logging", {}).get("level", "INFO")).upper()
        if level not in VALID_LEVELS:
            raise ConfigError(
                f"{source}: logging.level {level!r} is not one of {sorted(VALID_LEVELS)}"
            )
        self.log_level = level

    @staticmethod
    def _resolve(value):
        path = Path(value)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    def __repr__(self):
        return f"Config(source={self.source}, db_path={self.db_path}, log_level={self.log_level})"


def load_config(path=None):
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError(f"no config file at {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None
    return Config(data, path)

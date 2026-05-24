"""
Загрузка .env для dev-запуска и PyInstaller-сборки.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _candidate_env_paths() -> list[Path]:
    paths = []

    paths.append(Path.cwd() / ".env")

    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / ".env")

    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        paths.append(Path(bundle_dir) / ".env")

    project_root = Path(__file__).resolve().parents[2]
    paths.append(project_root / ".env")

    unique_paths = []
    seen = set()
    for path in paths:
        resolved = str(path)
        if resolved not in seen:
            unique_paths.append(path)
            seen.add(resolved)
    return unique_paths


def load_app_env() -> None:
    for path in _candidate_env_paths():
        if path.exists():
            load_dotenv(path, override=False)

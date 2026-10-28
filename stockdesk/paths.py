import os
from pathlib import Path


def data_dir():
    root = Path(os.environ.get("STOCKDESK_HOME", Path.home() / ".stockdesk"))
    root.mkdir(parents=True, exist_ok=True)
    return root

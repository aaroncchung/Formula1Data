from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from app.storage.local_storage import LocalStorage


class StorageService:
    """Storage facade that can later swap local files for S3/R2-compatible objects."""

    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.backend = LocalStorage(root or settings.data_dir)

    def read_json(self, path: str | Path) -> Any:
        return self.backend.read_json(path)

    def write_json(self, path: str | Path, data: Any) -> None:
        self.backend.write_json(path, data)

    def read_parquet(self, path: str | Path) -> pd.DataFrame:
        return self.backend.read_parquet(path)

    def write_parquet(self, path: str | Path, dataframe: pd.DataFrame) -> None:
        self.backend.write_parquet(path, dataframe)

    def exists(self, path: str | Path) -> bool:
        return self.backend.exists(path)

    def list(self, path: str | Path) -> list[str]:
        return self.backend.list(path)

    def delete(self, path: str | Path) -> None:
        self.backend.delete(path)

    def ensure_dir(self, path: str | Path) -> Path:
        return self.backend.ensure_dir(path)


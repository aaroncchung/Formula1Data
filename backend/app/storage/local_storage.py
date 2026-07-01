import json
from pathlib import Path
from typing import Any

import pandas as pd


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str | Path) -> Path:
        candidate = (self.root / Path(path)).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError(f"Path escapes storage root: {path}")
        return candidate

    def read_json(self, path: str | Path) -> Any:
        resolved = self.resolve(path)
        with resolved.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(self, path: str | Path, data: Any) -> None:
        resolved = self.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    def read_parquet(self, path: str | Path) -> pd.DataFrame:
        return pd.read_parquet(self.resolve(path))

    def write_parquet(self, path: str | Path, dataframe: pd.DataFrame) -> None:
        resolved = self.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_parquet(resolved, index=False)

    def exists(self, path: str | Path) -> bool:
        return self.resolve(path).exists()

    def list(self, path: str | Path) -> list[str]:
        resolved = self.resolve(path)
        if not resolved.exists():
            return []
        return [item.name for item in resolved.iterdir()]

    def delete(self, path: str | Path) -> None:
        resolved = self.resolve(path)
        if resolved.is_file():
            resolved.unlink()

    def ensure_dir(self, path: str | Path) -> Path:
        resolved = self.resolve(path)
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved


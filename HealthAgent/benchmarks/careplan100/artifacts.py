import json
from pathlib import Path
from threading import RLock

from .dataset import canonical, sha


class Artifacts:
    def __init__(self, path: Path, create=True):
        self.path = Path(path)
        if create: self.path.mkdir(parents=True, exist_ok=False)
        self.lock = RLock()

    def append(self, name, value):
        with self.lock, (self.path / name).open("ab") as f: f.write(canonical(value) + b"\n")

    def write(self, name, value):
        with self.lock:
            p = self.path / name; tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(canonical(value) + b"\n"); tmp.replace(p)

    def rows(self, name):
        p = self.path / name
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x] if p.exists() else []

    def file_hashes(self): return {p.name: sha(p.read_bytes()) for p in self.path.iterdir() if p.is_file() and p.name != "manifest.json"}

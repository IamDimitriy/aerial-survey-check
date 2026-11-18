import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parent
manifest = json.loads((root / "rezultaty-vinograd/report.json").read_text(encoding="utf-8"))["manifest"]
target = root / "istochniki"
target.mkdir(exist_ok=True)
for name, index in [("tz-vinograd-2023.pdf", 0), ("oam-uav.tif", 2)]:
    with urlopen(manifest["urls"][index], timeout=180) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != manifest["files"][name]["sha256"]:
        raise ValueError(f"Контрольная сумма источника изменилась: {name}")
    (target / name).write_bytes(data)

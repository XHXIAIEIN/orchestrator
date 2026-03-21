import hashlib
import re
import time
from pathlib import Path
from src.storage.events_db import EventsDB
from src.collectors.base import ICollector, CollectorMeta


def parse_vdf_simple(content: str) -> dict:
    result = {}
    for match in re.finditer(r'"(\w+)"\s+"([^"]*)"', content):
        result[match.group(1)] = match.group(2)
    return result


class SteamCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="steam", display_name="Steam", category="optional",
            env_vars=["STEAM_PATH"], requires=["steam"],
            event_sources=["steam"], default_enabled=False,
        )

    def __init__(self, db: EventsDB, steam_path: str = None):
        super().__init__(db)
        if steam_path is None:
            import os
            env_path = os.environ.get("STEAM_PATH")
            if env_path:
                self.steam_path = Path(env_path)
            else:
                candidates = [
                    Path("D:/Steam"),
                    Path("C:/Program Files (x86)/Steam"),
                    Path("C:/Program Files/Steam"),
                ]
                self.steam_path = next((p for p in candidates if p.exists()), None)
        else:
            self.steam_path = Path(steam_path)

    def collect(self) -> int:
        if not self.steam_path or not Path(self.steam_path).exists():
            return 0
        steamapps = Path(self.steam_path) / "steamapps"
        if not steamapps.exists():
            return 0

        new_count = 0
        for acf_file in steamapps.glob("appmanifest_*.acf"):
            try:
                content = acf_file.read_text(encoding="utf-8", errors="ignore")
                data = parse_vdf_simple(content)
                appid = data.get("appid", "")
                name = data.get("name", f"App {appid}")
                last_played = int(data.get("LastPlayed", 0))
                size_on_disk = int(data.get("SizeOnDisk", 0))
                if last_played == 0 and size_on_disk == 0:
                    continue
                days_since_played = (time.time() - last_played) / 86400 if last_played > 0 else 999
                dedup_key = hashlib.md5(f"steam:{appid}:{last_played}".encode()).hexdigest()
                score = max(0.1, min(1.0, 1.0 - days_since_played / 90))
                inserted = self.db.insert_event(
                    source="steam",
                    category="gaming",
                    title=name,
                    duration_minutes=0,
                    score=score,
                    tags=["gaming", "steam"],
                    metadata={"appid": appid, "last_played": last_played, "size_mb": size_on_disk // (1024 * 1024)},
                    dedup_key=dedup_key,
                )
                if inserted:
                    new_count += 1
            except (OSError, ValueError):
                continue
        return new_count

import hashlib
import re
from pathlib import Path
from src.storage.events_db import EventsDB


def parse_vdf_simple(content: str) -> dict:
    result = {}
    for match in re.finditer(r'"(\w+)"\s+"([^"]*)"', content):
        result[match.group(1)] = match.group(2)
    return result


class SteamCollector:
    def __init__(self, db: EventsDB, steam_path: str = None):
        self.db = db
        if steam_path is None:
            candidates = [
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
                playtime_forever = int(data.get("playtime_forever", 0))
                playtime_2weeks = int(data.get("playtime_2weeks", 0))
                if playtime_forever == 0:
                    continue
                dedup_key = hashlib.md5(f"steam:{appid}:{playtime_forever}".encode()).hexdigest()
                score = min(1.0, playtime_2weeks / 600) if playtime_2weeks > 0 else 0.1
                inserted = self.db.insert_event(
                    source="steam",
                    category="gaming",
                    title=name,
                    duration_minutes=playtime_forever,
                    score=score,
                    tags=["gaming", "steam"],
                    metadata={"appid": appid, "playtime_2weeks_min": playtime_2weeks},
                    dedup_key=dedup_key,
                )
                if inserted:
                    new_count += 1
            except (OSError, ValueError):
                continue
        return new_count

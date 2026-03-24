import pytest
from src.collectors.steam.collector import SteamCollector, parse_vdf_simple
from src.storage.events_db import EventsDB


def test_parse_vdf():
    vdf = '''
"AppState"
{
    "appid" "570"
    "name" "Dota 2"
    "playtime_forever" "1234"
    "playtime_2weeks" "60"
}
'''
    result = parse_vdf_simple(vdf)
    assert result.get("appid") == "570"
    assert result.get("name") == "Dota 2"
    assert result.get("playtime_forever") == "1234"


def test_collector_no_steam_returns_zero(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    collector = SteamCollector(db=db, steam_path=str(tmp_path / "nonexistent"))
    count = collector.collect()
    assert count == 0

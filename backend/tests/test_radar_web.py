from app.radar import fanqie_web
from app.radar.fanqie_charset import CODE_START


def test_decode_and_parse():
    enc = chr(CODE_START + 1) + "诡异"  # 0xE3E9 -> 在
    assert fanqie_web.decode(enc) == "在诡异"
    payload = {"code": 0, "data": {"rankVersion": "1", "book_list": [
        {"bookId": "1", "bookName": enc, "author": "a", "currentPos": "2", "rankPosDiff": "-3",
         "read_count": "1,234", "wordNumber": "5000", "abstract": "x\n y", "creationStatus": "0"},
        {"bookId": "2", "bookName": ""},
    ]}}
    items = fanqie_web.parse_board(payload, "female", "古风世情")
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "在诡异" and it["rank"] == 2 and it["rank_diff"] == -3
    assert it["read_count"] == 1234 and it["gender"] == "female" and it["category"] == "古风世情"
    assert it["abstract"] == "x y" and "完结" in it["tags"]


def test_refresh_dedupes_same_version(client, monkeypatch):
    from app.radar import service
    calls = {"n": 0}

    def fake(per_board=None, progress=None):
        calls["n"] += 1
        return ([{"book_id_ext": "9", "title": "t", "author": "", "category": "都市日常", "rank": 1, "rank_diff": 2,
                  "read_count": 10, "word_count": 1, "abstract": "", "tags": [], "gender": "male"}], "v1")

    monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists", fake)
    monkeypatch.setattr(service, "get_config", lambda s: {"enabled": True, "daily_hour": 8})

    class Ctx:
        def progress(self, *a, **k):
            pass

    r1 = service.refresh(Ctx())
    r2 = service.refresh(Ctx())
    assert r1["source"] == "web" and not r1.get("unchanged")
    assert r2.get("unchanged") and r2["snapshot_id"] == r1["snapshot_id"]
    latest = client.get("/api/radar/latest", params={"gender": "male"}).json()
    assert latest["items"][0]["rank_diff"] == 2
    trends = client.get("/api/radar/trends", params={"gender": "male"}).json()
    assert trends[0]["rising"] == 1

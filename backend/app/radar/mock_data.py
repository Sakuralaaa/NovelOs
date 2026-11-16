"""雷达 mock 榜单：50 条像样的假数据（男女频、多分类）。按日期做小幅确定性扰动，让“上升”有意义。

书名、作者均为虚构，与任何真实作品无关。
"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Any

_MALE: list[tuple[str, list[str]]] = [
    ("都市高武", ["全民觉醒：我的天赋是加点", "高武：开局一刀斩九境", "我在都市修杀戮道", "武道通神，从送外卖开始", "高考满分后，我被武大抢疯了"]),
    ("玄幻脑洞", ["我的宗门全是隐藏大佬", "开局签到荒古圣体", "被退婚后，我觉醒了吞天魔功", "师尊别装了，我都知道", "我养的灵宠都是神兽"]),
    ("悬疑灵异", ["诡异复苏：我能看见死亡倒计时", "我在凶宅当保安", "无限恐怖：开局直播通关", "民俗诡事录", "规则怪谈：千万别回头"]),
    ("历史古代", ["大明：我朱元璋的崽", "穿越三国，我开局抢了赤兔", "大唐：从长安小吏到宰相", "北宋：我在汴京开酒楼", "抗战：我的系统能召唤援军"]),
    ("科幻末世", ["末世：我囤了十亿物资", "冰封末日：我在避难所种田", "星际机甲：废柴驾驶员", "全球废土：开局一辆房车", "天灾降临，我建造了方舟"]),
    ("都市日常", ["重生九零：我在小县城当首富", "神豪：每天到账一个亿", "我在乡下开民宿", "退役后，我成了全村的希望", "离婚后，我被富婆包养了"]),
]
_FEMALE: list[tuple[str, list[str]]] = [
    ("现言甜宠", ["闪婚后，冷面总裁天天想贴贴", "被大佬盯上后，我躺赢了", "顶流的白月光是我", "隐婚三年，影帝官宣了", "她是豪门真千金"]),
    ("豪门总裁", ["离婚后，前夫跪求复合", "替嫁新娘：总裁的契约妻", "五年后，她带三宝炸翻全城", "总裁夫人又在掉马甲", "豪门弃妇的逆袭"]),
    ("宫斗宅斗", ["嫡女重生：这一世我只为自己", "冷宫弃妃：皇上请自重", "庶女谋：步步为营", "侯门主母不好当", "重生后，我把渣男送进了天牢"]),
    ("年代", ["七零：下乡知青有空间", "八零小厨娘，靠美食养全家", "重回九零：我嫁给了糙汉", "六零年代：带着系统去随军", "年代文里的炮灰觉醒了"]),
    ("快穿", ["快穿：炮灰女配不干了", "快穿之反派他又在黑化", "宿主她只想搞事业", "快穿：我在小世界当白月光", "穿书后我成了恶毒女配"]),
]
_AUTHORS = ["青山不语", "夜听雨", "南风知我意", "北冥有鱼", "半盏清茶", "墨染江湖", "一叶知秋", "苏打水", "糖醋排骨", "月下独酌",
            "白鹭成双", "长歌当哭", "鹿鸣", "锦瑟", "孤城闭"]
_ABSTRACT_M = "主角在绝境中觉醒金手指，一路打脸逆袭，揭开隐藏在世界背后的真相。"
_ABSTRACT_F = "她重生归来，手握先知，步步为营，把欠她的一一讨回，也遇见了真正护她的人。"


def mock_rank_items(day: date | None = None) -> list[dict[str, Any]]:
    day = day or date.today()
    rng = random.Random(int(hashlib.md5(day.isoformat().encode()).hexdigest()[:8], 16))
    items: list[dict[str, Any]] = []
    for gender, groups in (("male", _MALE), ("female", _FEMALE)):
        pool: list[dict[str, Any]] = []
        for cat, titles in groups:
            for t in titles:
                h = int(hashlib.md5(t.encode()).hexdigest()[:8], 16)
                base = 50_000 + h % 900_000
                read = int(base * rng.uniform(0.7, 1.4))
                pool.append({
                    "book_id_ext": f"mock{h % 10**10:010d}",
                    "title": t,
                    "author": _AUTHORS[h % len(_AUTHORS)],
                    "category": cat,
                    "read_count": read,
                    "word_count": 80_000 + (h % 2_000_000),
                    "abstract": _ABSTRACT_F if gender == "female" else _ABSTRACT_M,
                    "tags": [cat, ["系统", "重生", "爽文", "逆袭", "甜宠", "穿越"][h % 6]],
                    "gender": gender,
                    "board": "read",
                })
        pool.sort(key=lambda x: -x["read_count"])
        for i, it in enumerate(pool, 1):
            it["rank"] = i
        items.extend(pool)
    return items  # 男频 30 + 女频 25 = 55 条；前 50 条以内覆盖全部分类


def mock_items_50(day: date | None = None) -> list[dict[str, Any]]:
    items = mock_rank_items(day)
    male = [i for i in items if i["gender"] == "male"][:27]
    female = [i for i in items if i["gender"] == "female"][:23]
    return male + female


# v0.9：新书榜示例（30 万字以下的新书），同样是虚构书名
_MALE_NEW: list[tuple[str, list[str]]] = [
    ("都市脑洞", ["我的外卖箱能通往三天后", "退休金到账，我成了城隍爷", "开局继承一座倒闭游乐园"]),
    ("悬疑脑洞", ["规则怪谈：夜班保安守则第七条", "我能听见遗物说话", "停尸间的第十三个抽屉"]),
    ("玄幻脑洞", ["宗门要倒闭，我把灵田包出去了", "被逐出师门后，我开了家修仙驾校", "我的剑灵只会吐槽"]),
]
_FEMALE_NEW: list[tuple[str, list[str]]] = [
    ("现言脑洞", ["离婚冷静期，我听见了老公的心声", "全家读我心后，炮灰剧情崩了", "被赶出豪门，我靠直播算命爆红"]),
    ("古言脑洞", ["王妃她只想种地发家", "替嫁冲喜，病秧子夫君装不下去了", "重生后我把渣夫送去和亲"]),
]


def mock_new_items(day: date | None = None) -> list[dict[str, Any]]:
    """新书榜示例：男频 9 + 女频 6 = 15 条，字数都在 30 万以内。"""
    day = day or date.today()
    rng = random.Random(int(hashlib.md5(("new" + day.isoformat()).encode()).hexdigest()[:8], 16))
    items: list[dict[str, Any]] = []
    for gender, groups in (("male", _MALE_NEW), ("female", _FEMALE_NEW)):
        pool: list[dict[str, Any]] = []
        for cat, titles in groups:
            for t in titles:
                h = int(hashlib.md5(("new" + t).encode()).hexdigest()[:8], 16)
                pool.append({
                    "book_id_ext": f"mocknew{h % 10**8:08d}",
                    "title": t,
                    "author": _AUTHORS[h % len(_AUTHORS)],
                    "category": cat,
                    "read_count": int((5_000 + h % 80_000) * rng.uniform(0.7, 1.5)),
                    "word_count": 30_000 + h % 260_000,
                    "abstract": _ABSTRACT_F if gender == "female" else _ABSTRACT_M,
                    "tags": [cat, "连载"],
                    "gender": gender,
                    "board": "new",
                    "rank_diff": rng.choice([0, 0, 1, 3, -2, 5]),
                })
        pool.sort(key=lambda x: -x["read_count"])
        for i, it in enumerate(pool, 1):
            it["rank"] = i
        items.extend(pool)
    return items

"""v0.20 可插拔技能库服务：内置方法论初始化、CRUD、按书挂载、GitHub SKILL.md 导入。"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.db import kv_get, kv_set, session_scope
from app.models.tables import Book, BookSkill, Skill, utcnow
from app.skills.loader import builtin_names, default_text, platform_filter

SKILL_STAGES = (
    "writing", "outline", "chapter_plan", "bible", "ideation",
    "review", "humanize", "teardown", "package", "trend_report", "general",
)

STAGE_LABELS: dict[str, str] = {
    "writing": "正文写作",
    "outline": "大纲规划",
    "chapter_plan": "章细纲",
    "bible": "设定库",
    "ideation": "选题立项",
    "review": "审稿把关",
    "humanize": "去 AI 味",
    "teardown": "拆书分析",
    "package": "包装简介",
    "trend_report": "风向标",
    "general": "通用方法",
}

# 精选 MIT 思路内置网文方法论技能（默认不自动叠加到所有书，按需勾选，避免规则打架）
CURATED_SKILLS: list[dict[str, Any]] = [
    {
        "slug": "curated-golden-opening",
        "name": "黄金三章开篇技法",
        "description": "番茄/起点开篇前三章节奏：前三行入局、主角当场行动、金手指露苗头与首次小胜结算。",
        "stage": "writing",
        "license": "MIT",
        "source_url": "curated/webnovel-golden-opening",
        "is_default": False,
        "body": """# 黄金三章开篇技法

1. **第 1 章（入局）**：前三行直接把冲突、危机或反常抛在读者眼前，不做大段世界观科普；主角一出场就在做具体动作并撞上麻烦。
2. **金手指苗头**：第 1 章内必须让核心金手指露出读者能感知的苗头或触发线索，交代清楚它怎么触发、目前有什么边界。
3. **第 2 章（加压与初试）**：对手加码施压，主角主动利用金手指或信息差做出一次反击，写出看得见的阶段收益。
4. **第 3 章（小胜与承诺）**：完成第一次完整打脸/收益结算（资源、名次、身份或认可至少兑现一项），并引出更高一层的长线目标。
5. **信息克制**：背景设定只在角色此刻要用、碰得到的时候顺嘴带出，一次只交代一件。""",
    },
    {
        "slug": "curated-payoff-rhythm",
        "name": "爽点三拍与压抑释放",
        "description": "写满「期待 → 压抑 → 释放」三拍，释放时写清谁输、怎么输、谁在场看见、主角拿到什么。",
        "stage": "writing",
        "license": "MIT",
        "source_url": "curated/webnovel-payoff-rhythm",
        "is_default": False,
        "body": """# 爽点三拍与压抑释放

1. **第一拍·立期待**：提前让读者知道主角想要什么、或者如果成了能拿到多大的好处/反转。
2. **第二拍·给足压抑**：对手不是草包，拦路理由要具体、压迫感要真实，让读者心里替主角憋着一口气。
3. **第三拍·痛快释放**：主角用自己的算盘/能力破局时，正面写出四件事：
   - 谁输了、怎么输的（动作与表情具体化）；
   - 谁在场看见了（第三方反应只给 1–2 个有分量的镜头，别堆路人齐呼）；
   - 主角拿到什么可比较的具体收益（数字、境界、资源、资格）；
   - 顺手带出下一层更大的局。""",
    },
    {
        "slug": "curated-chapter-hooks",
        "name": "章末悬念与跨章衔接",
        "description": "章末停在动作刚出手、台词刚落定或变故刚砸下的半拍上，严禁总结升华式收尾。",
        "stage": "writing",
        "license": "MIT",
        "source_url": "curated/webnovel-chapter-hooks",
        "is_default": False,
        "body": """# 章末悬念与跨章衔接

1. **章首紧接**：开篇第一段直接接住上一章末尾的动作、对白或情绪，不要重新总结「昨日发生了什么」。
2. **章末断在半拍**：最后一段只落一个主钩子，停在以下四种瞬间之一：
   - 新的人/势力突然推门或发声；
   - 关键消息、面板提示或反转证据刚亮出来；
   - 主角或对手刚出手/亮底牌；
   - 一句带信息差或火药味的台词。
3. **禁止总结腔**：结尾绝不写「他知道，一场更大的风暴正在酝酿」「属于他的时代才刚刚开始」这类旁白总结。""",
    },
    {
        "slug": "curated-de-ai-prose",
        "name": "去 AI 味与口语质感",
        "description": "消除翻译腔、翻案腔、高频强化词与空洞形容，把情绪和心理藏进具体动作与对白里。",
        "stage": "humanize",
        "license": "MIT",
        "source_url": "curated/webnovel-de-ai-prose",
        "is_default": False,
        "body": """# 去 AI 味与口语质感

1. **去套话与高频副词**：少用「死死、硬生生、不由得、一丝、一抹、刹那间、令人窒息、空气仿佛凝固、嘴角勾起一抹冷笑」等高频词。
2. **去翻案腔**：少写「不是……而是……」「与其说……不如说……」这类议论文句式。
3. **动作替抽象**：把「他非常愤怒/极为震惊」改成他手里的动作、停顿、改口或眼神落点。
4. **对白带目的**：人物开口不是为了替作者解释设定，每句台词都要有试探、掩饰、威胁或交易的目的。""",
    },
    {
        "slug": "curated-teardown-structure",
        "name": "爆款结构拆书方法论",
        "description": "只学骨架不抄皮：拆解核心卖点公式、金手指兑现周期、冲突换型与必须替换清单。",
        "stage": "teardown",
        "license": "MIT",
        "source_url": "curated/webnovel-teardown-structure",
        "is_default": False,
        "body": """# 爆款结构拆书方法论

拆解任何一本热榜作品时，按以下五个维度输出可复用的结构笔记：
1. **核心钩子与情绪承诺**：读者为什么点开第一章？在等哪一种情绪兑现？
2. **金手指机制**：输入条件 → 产出物 → 现阶段上限 → 成长曲线 → 首次兑现在第几章。
3. **前 10 章阻力换型**：记录每章冲突类型（武力/利益/身份/规则/悬疑/情感），观察它如何避免连续 3 章重复同一种刁难。
4. **可借鉴骨架**：节奏配比、信息差制造方式、配角功能位。
5. **必须换掉的皮**：世界观外壳、人设标签、金手指表现形式、专有名词。""",
    },
    {
        "slug": "curated-tomato-shortdrama-plain",
        "name": "番茄完本·短剧强情绪大白话",
        "description": "面向番茄完本签约与红果短剧改编：2000字短章、三句强情绪开场、零专业黑话纯大白话、强镜头动作感。",
        "stage": "writing",
        "license": "MIT",
        "source_url": "curated/tomato-shortdrama-plain",
        "is_default": False,
        "body": """# 番茄完本·短剧强情绪大白话

1. **三句入戏（短剧开场）**：开篇前三句必须直接落进高情绪冲突对白或眼前变故，严禁铺垫背景、描写天气或大段心理独白。
2. **金手指可板正，人话必通俗**：系统提示或面板文字可以保留一点官方、板正的反差感；但主角和配角的台词、旁白叙述、章节标题必须说大白话，严禁高频堆砌金融、法务、学术或晦涩术语（能让初中生一眼看懂算过关）。
3. **短剧镜头感**：人物外貌、穿着、道具、微动作和神态要具体可拍，情绪藏在停顿、眼神、掀桌、摔门和狠话里，不写「他无比愤怒」「气氛骤然凝固」这类抽象标签。
4. **2000–2300 字黄金短章与手机短段**：每章严格控制在 2000–2300 字，多数段落不超过 65 字（1–3 句一段），对白独立成段；单章只打透一个核心冲突和一次痛快兑现，绝不注水。
5. **章末半拍卡点**：停在反转刚露头、底牌刚掀开或一句带火药味的台词上，严禁写玄幻式白光咆哮与「风暴正在酝酿」式总结。""",
    },
    {
        "slug": "curated-heavy-outline-beat",
        "name": "重纲轻写·千字起承转合章纲",
        "description": "每章细纲按「起/承/转/合」写到 800–1000 字，配齐核心场景、底层博弈与本章收益，按 1:2 比例扩写成强节奏正文。",
        "stage": "chapter_plan",
        "license": "MIT",
        "source_url": "curated/heavy-outline-beat",
        "is_default": False,
        "body": """# 重纲轻写·千字起承转合章纲

1. **高密度章纲（1:2 扩写比）**：每章细纲写足 800–1000 字，扩写成 2000–2200 字正文，杜绝写手临场注水或偏离主线。
2. **四拍拆解**：
   - **起（入局钩子）**：前三句直接砸下的冲突画面、对白引爆点与在场人物状态。
   - **承（加压博弈）**：对手如何步步紧逼、主角藏了什么暗手、信息差怎么一步步拉满。
   - **转（反转爆点）**：金手指或底牌如何亮出、谁当众翻车、具体怎么输、围观者的真实反应。
   - **合（收益与悬念）**：主角落袋的具体可比较收益，以及停在半拍上的章末强钩子。
3. **落地三检查**：每章明确「核心场景」「底层博弈」「本章收益」，确保相邻章节不重复同一种打脸套路，每 3 章至少有一次清晰可感知的金手指兑现。""",
    },
]


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    body = text or ""
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            fm, body = parts[1], parts[2]
            for line in fm.splitlines():
                if ":" in line and not line.strip().startswith("- "):
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, body.strip()


def _builtin_rule_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in builtin_names("rules"):
        raw = default_text("rules", name)
        meta, body = _parse_frontmatter(raw)
        stage = meta.get("stage") or (name if name in SKILL_STAGES else "general")
        if name == "duanju":
            stage = "writing"
        rows.append({
            "slug": f"builtin-rule-{name}",
            "name": meta.get("title") or STAGE_LABELS.get(stage, name),
            "description": f"NovelOS 内置「{STAGE_LABELS.get(stage, name)}」核心规则包，可自由修改或重置。",
            "stage": stage,
            "body": body,
            "source": "builtin",
            "source_url": f"builtin/rules/{name}.md",
            "license": "Apache-2.0",
            "enabled": True,
            "is_default": name != "duanju",  # 短剧分镜按需启用，其余内置规则默认启用
        })
    return rows


def seed_builtin_skills() -> int:
    """幂等初始化内置技能：已存在的 slug 绝不覆盖（保护用户的修改）。返回本次新增条数。"""
    added = 0
    all_defs = [*_builtin_rule_rows(), *[{**x, "source": "builtin", "enabled": True} for x in CURATED_SKILLS]]
    with session_scope() as s:
        existing = {sk.slug for sk in s.exec(select(Skill)).all()}
        for d in all_defs:
            if d["slug"] in existing:
                continue
            s.add(Skill(
                slug=d["slug"],
                name=d["name"],
                description=d.get("description") or "",
                stage=d.get("stage") or "general",
                body=d.get("body") or "",
                references=list(d.get("references") or []),
                source=d.get("source") or "builtin",
                source_url=d.get("source_url") or "",
                license=d.get("license") or "",
                enabled=bool(d.get("enabled", True)),
                is_default=bool(d.get("is_default", False)),
            ))
            added += 1
        if added:
            s.commit()
    return added


def default_builtin_body(slug: str) -> dict[str, Any] | None:
    for d in [*_builtin_rule_rows(), *[{**x, "source": "builtin", "enabled": True} for x in CURATED_SKILLS]]:
        if d["slug"] == slug:
            return d
    return None


def skill_out(sk: Skill, with_body: bool = True) -> dict[str, Any]:
    ref_chars = sum(len(str(r.get("content") or "")) for r in (sk.references or []) if isinstance(r, dict))
    d: dict[str, Any] = {
        "id": sk.id,
        "slug": sk.slug,
        "name": sk.name,
        "description": sk.description,
        "stage": sk.stage,
        "source": sk.source,
        "source_url": sk.source_url,
        "license": sk.license,
        "enabled": sk.enabled,
        "is_default": sk.is_default,
        "chars": len(sk.body or "") + ref_chars,
        "ref_count": len(sk.references or []),
        "created_at": sk.created_at.isoformat() if sk.created_at else None,
        "updated_at": sk.updated_at.isoformat() if sk.updated_at else None,
    }
    if with_body:
        d["body"] = sk.body
        d["references"] = sk.references or []
    return d


def _book_custom_key(book_id: int) -> str:
    return f"book_skills_custom:{book_id}"


def book_skill_ids(s: Session, book_id: int) -> tuple[bool, list[int]]:
    """返回 (是否按书自定义过, 绑定的 skill_id 列表)。"""
    custom = bool(kv_get(s, _book_custom_key(book_id), False))
    rows = s.exec(select(BookSkill).where(BookSkill.book_id == book_id).order_by(BookSkill.order, BookSkill.id)).all()
    if custom:
        return True, [r.skill_id for r in rows]
    defaults = s.exec(select(Skill).where(Skill.enabled == True, Skill.is_default == True).order_by(Skill.id)).all()  # noqa: E712
    return False, [sk.id for sk in defaults if sk.id is not None]


def set_book_skills(s: Session, book_id: int, skill_ids: list[int]) -> list[int]:
    if s.get(Book, book_id) is None:
        raise ValueError("作品不存在")
    old = s.exec(select(BookSkill).where(BookSkill.book_id == book_id)).all()
    for r in old:
        s.delete(r)
    valid_ids = {sk.id for sk in s.exec(select(Skill)).all() if sk.id is not None}
    clean: list[int] = []
    for idx, sid in enumerate(skill_ids):
        i = int(sid)
        if i in valid_ids and i not in clean:
            clean.append(i)
            s.add(BookSkill(book_id=book_id, skill_id=i, order=idx))
    kv_set(s, _book_custom_key(book_id), True)
    s.commit()
    return clean


def active_skills_for_book(s: Session, book_id: int, stage: str) -> list[Skill]:
    """获取某本书在指定环节（stage）生效的技能列表。"""
    custom, ids = book_skill_ids(s, book_id)
    if not ids:
        return []
    by_id = {sk.id: sk for sk in s.exec(select(Skill).where(Skill.id.in_(ids))).all() if sk.id is not None}  # type: ignore[attr-defined]
    out: list[Skill] = []
    for sid in ids:
        sk = by_id.get(sid)
        if sk is None or not sk.enabled:
            continue
        if sk.stage == stage or (custom and sk.stage == "general"):
            out.append(sk)
    return out


def render_skills_text(skills: list[Skill], platform: str | None = None) -> str:
    """把生效技能列表拼成供写作/规划使用的规则文本（兼容 <!-- platform:xxx --> 分平台小节）。"""
    parts: list[str] = []
    for sk in skills:
        body = platform_filter(sk.body or "", platform)
        if not body:
            continue
        block = body
        if not block.lstrip().startswith("#"):
            block = f"## {sk.name}\n{block}"
        refs = [r for r in (sk.references or []) if isinstance(r, dict) and str(r.get("content") or "").strip()]
        if refs:
            ref_txt = "\n\n".join(f"### 参考：{r.get('name') or '资料'}\n{str(r.get('content')).strip()}" for r in refs[:5])
            block = block + "\n\n" + ref_txt
        parts.append(block)
    return "\n\n".join(parts).strip()


# ------------------------------------------------------------------ GitHub 导入（兼容 Claude SKILL.md）

_GH_BLOB = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")
_GH_TREE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*))?$")
_GH_REPO = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", (name or "").strip().lower()).strip("-")
    base = s[:40] if s else "skill"
    return f"{base}-{secrets.token_hex(3)}"


def _gh_headers(token: str | None = None) -> dict[str, str]:
    tk = (token or os.environ.get("GITHUB_TOKEN") or "").strip()
    h = {"Accept": "application/vnd.github+json", "User-Agent": "NovelOS-Skill-Importer"}
    if tk:
        h["Authorization"] = f"Bearer {tk}"
    return h


def parse_github_url(url: str) -> dict[str, str]:
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        raise ValueError("请输入完整的 GitHub 链接（https://...）")
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    if host == "raw.githubusercontent.com":
        return {"kind": "raw", "url": u}
    m = _GH_BLOB.match(u)
    if m:
        owner, repo, branch, path = m.groups()
        return {"kind": "blob", "owner": owner, "repo": repo, "branch": branch, "path": path}
    m = _GH_TREE.match(u)
    if m:
        owner, repo, branch, path = m.group(1), m.group(2), m.group(3), (m.group(4) or "").strip("/")
        return {"kind": "tree", "owner": owner, "repo": repo, "branch": branch, "path": path}
    m = _GH_REPO.match(u)
    if m:
        owner, repo = m.groups()
        return {"kind": "repo", "owner": owner, "repo": repo, "branch": "main", "path": ""}
    raise ValueError("仅支持 github.com 或 raw.githubusercontent.com 的仓库/目录/文件链接")


def fetch_github_skill(url: str, stage: str | None = None, token: str | None = None) -> dict[str, Any]:
    """从 GitHub 抓取 SKILL.md（及可选 references/*.md），返回待入库的技能字典。"""
    info = parse_github_url(url)
    hdrs = _gh_headers(token)
    refs: list[dict[str, str]] = []
    license_name = ""
    fallback_name = "imported-skill"

    with httpx.Client(timeout=20, follow_redirects=True, headers=hdrs) as c:
        if info["kind"] == "raw":
            r = c.get(info["url"])
            r.raise_for_status()
            raw_text = r.text
            fallback_name = info["url"].rstrip("/").rsplit("/", 1)[-1].removesuffix(".md")
        elif info["kind"] == "blob":
            raw_url = f"https://raw.githubusercontent.com/{info['owner']}/{info['repo']}/{info['branch']}/{info['path']}"
            r = c.get(raw_url)
            r.raise_for_status()
            raw_text = r.text
            fallback_name = info["path"].rstrip("/").rsplit("/", 1)[-1].removesuffix(".md")
            if fallback_name.lower() == "skill" and "/" in info["path"]:
                fallback_name = info["path"].rsplit("/", 2)[-2]
        else:
            owner, repo, branch, path = info["owner"], info["repo"], info["branch"], info["path"]
            fallback_name = (path.rsplit("/", 1)[-1] if path else repo) or repo
            # 依次尝试 SKILL.md / README.md（repo 模式若 main 404 再试 master）
            branches = [branch] if info["kind"] == "tree" else ["main", "master"]
            raw_text = ""
            picked_branch = branch
            for br in branches:
                for fname in ("SKILL.md", "skill.md", "README.md"):
                    sub = f"{path}/{fname}" if path else fname
                    r = c.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{br}/{sub}")
                    if r.status_code == 200 and r.text.strip():
                        raw_text = r.text
                        picked_branch = br
                        break
                if raw_text:
                    break
            if not raw_text:
                raise ValueError("在该 GitHub 路径下未找到 SKILL.md 或 README.md")
            # 尝试拉取同目录下的 references/*.md（最多 5 个，失败不阻塞）
            try:
                ref_path = f"{path}/references" if path else "references"
                rr = c.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{ref_path}", params={"ref": picked_branch})
                if rr.status_code == 200 and isinstance(rr.json(), list):
                    for item in rr.json()[:5]:
                        dl = str(item.get("download_url") or "") if isinstance(item, dict) else ""
                        dl_parsed = urlparse(dl)
                        if (
                            isinstance(item, dict)
                            and str(item.get("name", "")).endswith(".md")
                            and dl_parsed.scheme == "https"
                            and (dl_parsed.hostname or "").lower() in ("raw.githubusercontent.com", "github.com")
                        ):
                            rc = c.get(dl)
                            if rc.status_code == 200 and rc.text.strip():
                                refs.append({"name": str(item["name"]), "content": rc.text.strip()[:12000]})
            except Exception:  # noqa: BLE001
                pass

    meta, body = _parse_frontmatter(raw_text)
    if not body.strip():
        raise ValueError("导入的技能文件内容为空")
    name = meta.get("name") or meta.get("title") or fallback_name
    desc = meta.get("description") or ""
    chosen_stage = stage or meta.get("stage") or "writing"
    if chosen_stage not in SKILL_STAGES:
        chosen_stage = "general"
    return {
        "slug": _slugify(name),
        "name": name[:80],
        "description": desc[:300],
        "stage": chosen_stage,
        "body": body[:40000],
        "references": refs,
        "source": "github",
        "source_url": url.strip(),
        "license": meta.get("license") or license_name,
        "enabled": True,
        "is_default": False,
    }

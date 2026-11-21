"""v0.20 可插拔技能库接口：CRUD、复制、重置内置、GitHub 导入、作品绑定。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models.tables import Book, BookSkill, Skill, utcnow
from app.services import skills_store as svc

router = APIRouter(prefix="/api")


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    stage: str = "writing"
    body: str = Field(min_length=1, max_length=60000)
    references: list[dict[str, Any]] = []
    enabled: bool = True
    is_default: bool = False
    license: str = ""
    source_url: str = ""


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    stage: str | None = None
    body: str | None = Field(default=None, min_length=1, max_length=60000)
    references: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class GithubImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    stage: str | None = None
    token: str | None = None


class BookSkillsIn(BaseModel):
    skill_ids: list[int] = []


@router.get("/skills")
def list_skills(stage: str | None = None, source: str | None = None, q: str = "",
                s: Session = Depends(get_session)) -> dict[str, Any]:
    rows = s.exec(select(Skill).order_by(Skill.source, Skill.stage, Skill.id)).all()
    if stage:
        rows = [r for r in rows if r.stage == stage]
    if source:
        rows = [r for r in rows if r.source == source]
    kw = (q or "").strip().lower()
    if kw:
        rows = [r for r in rows if kw in f"{r.name} {r.description} {r.body}".lower()]
    return {
        "stages": [{"key": k, "label": svc.STAGE_LABELS.get(k, k)} for k in svc.SKILL_STAGES],
        "items": [svc.skill_out(r, with_body=True) for r in rows],
    }


@router.get("/skills/{skill_id}")
def get_skill(skill_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    sk = s.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(404, "技能不存在")
    return svc.skill_out(sk, with_body=True)


@router.post("/skills")
def create_skill(body: SkillIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    stage = body.stage if body.stage in svc.SKILL_STAGES else "general"
    sk = Skill(
        slug=svc._slugify(body.name),
        name=body.name.strip(),
        description=body.description.strip(),
        stage=stage,
        body=body.body.strip(),
        references=body.references,
        source="custom",
        source_url=body.source_url.strip(),
        license=body.license.strip() or "custom",
        enabled=body.enabled,
        is_default=body.is_default,
    )
    s.add(sk)
    s.commit()
    s.refresh(sk)
    return svc.skill_out(sk, with_body=True)


@router.put("/skills/{skill_id}")
def update_skill(skill_id: int, body: SkillUpdate, s: Session = Depends(get_session)) -> dict[str, Any]:
    sk = s.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(404, "技能不存在")
    data = body.model_dump(exclude_unset=True)
    if "stage" in data and data["stage"] not in svc.SKILL_STAGES:
        raise HTTPException(400, f"不支持的环节：{data['stage']}")
    for k, v in data.items():
        if v is not None:
            setattr(sk, k, v.strip() if isinstance(v, str) else v)
    sk.updated_at = utcnow()
    s.add(sk)
    s.commit()
    s.refresh(sk)
    return svc.skill_out(sk, with_body=True)


@router.post("/skills/{skill_id}/duplicate")
def duplicate_skill(skill_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    src = s.get(Skill, skill_id)
    if src is None:
        raise HTTPException(404, "技能不存在")
    copy = Skill(
        slug=svc._slugify(src.name),
        name=f"{src.name}（副本）"[:80],
        description=src.description,
        stage=src.stage,
        body=src.body,
        references=list(src.references or []),
        source="custom",
        source_url=src.source_url,
        license=src.license,
        enabled=True,
        is_default=False,
    )
    s.add(copy)
    s.commit()
    s.refresh(copy)
    return svc.skill_out(copy, with_body=True)


@router.post("/skills/{skill_id}/reset")
def reset_skill(skill_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    sk = s.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(404, "技能不存在")
    orig = svc.default_builtin_body(sk.slug)
    if orig is None:
        raise HTTPException(400, "只有内置技能可以重置为初始版本")
    sk.name = orig["name"]
    sk.description = orig.get("description") or ""
    sk.stage = orig.get("stage") or sk.stage
    sk.body = orig.get("body") or ""
    sk.references = list(orig.get("references") or [])
    sk.updated_at = utcnow()
    s.add(sk)
    s.commit()
    s.refresh(sk)
    return svc.skill_out(sk, with_body=True)


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    sk = s.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(404, "技能不存在")
    if sk.source == "builtin":
        raise HTTPException(409, "内置技能不可删除，可以停用或修改")
    for link in s.exec(select(BookSkill).where(BookSkill.skill_id == skill_id)).all():
        s.delete(link)
    s.delete(sk)
    s.commit()
    return {"ok": True}


@router.post("/skills/import-github")
def import_github_skill(body: GithubImportIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        data = svc.fetch_github_skill(body.url, stage=body.stage, token=body.token)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"导入失败：{e}") from e
    sk = Skill(**data)
    s.add(sk)
    s.commit()
    s.refresh(sk)
    return svc.skill_out(sk, with_body=True)


@router.get("/books/{book_id}/skills")
def get_book_skills(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    if s.get(Book, book_id) is None:
        raise HTTPException(404, "作品不存在")
    custom, ids = svc.book_skill_ids(s, book_id)
    all_rows = s.exec(select(Skill).order_by(Skill.stage, Skill.source, Skill.id)).all()
    selected = set(ids)
    writing_chars = sum(
        len(r.body or "") + sum(len(str(x.get("content") or "")) for x in (r.references or []) if isinstance(x, dict))
        for r in all_rows if r.id in selected and r.enabled and r.stage in ("writing", "general")
    )
    return {
        "book_id": book_id,
        "customized": custom,
        "selected_ids": ids,
        "writing_chars": writing_chars,
        "items": [svc.skill_out(r, with_body=False) for r in all_rows],
    }


@router.put("/books/{book_id}/skills")
def put_book_skills(book_id: int, body: BookSkillsIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    svc.set_book_skills(s, book_id, body.skill_ids)
    return get_book_skills(book_id, s)

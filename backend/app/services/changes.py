"""---CHANGES--- 变更声明：解析、schema 校验、对照底账检查。"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

CHANGES_MARKER = "---CHANGES---"
CARD_TYPES = ("world", "cheat", "power", "faction", "character", "item", "location")


class NewEntity(BaseModel):
    type: str = "character"
    name: str = Field(min_length=1, max_length=40)
    summary: str = ""

    @field_validator("type")
    @classmethod
    def _t(cls, v: str) -> str:
        return v if v in CARD_TYPES else "character"


class StateChange(BaseModel):
    entity: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: str
    visibility: Literal["author", "reader"] = "reader"

    @field_validator("value", mode="before")
    @classmethod
    def _v(cls, v: Any) -> str:
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


class ForeshadowAction(BaseModel):
    action: Literal["plant", "advance", "resolve"]
    id: int | None = None
    desc: str = ""


class ChangeSet(BaseModel):
    new_entities: list[NewEntity] = []
    state_changes: list[StateChange] = []
    foreshadow: list[ForeshadowAction] = []


def split_output(text: str) -> tuple[str, str | None]:
    """把模型输出拆成（正文, 变更 JSON 原文）。取最后一个标记。"""
    idx = text.rfind(CHANGES_MARKER)
    if idx == -1:
        return text.strip(), None
    return text[:idx].strip(), text[idx + len(CHANGES_MARKER) :].strip()


def parse_changes(raw: str | None) -> tuple[ChangeSet, list[str]]:
    """解析并校验变更声明；非法条目逐条丢弃并给出警告，不让整章失败。"""
    warnings: list[str] = []
    if raw is None:
        return ChangeSet(), ["正文未附 ---CHANGES--- 变更声明，按无变更处理"]
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    a, b = t.find("{"), t.rfind("}")
    try:
        data = json.loads(t[a : b + 1]) if a != -1 and b > a else json.loads(t)
    except json.JSONDecodeError:
        return ChangeSet(), ["变更声明不是合法 JSON，已忽略"]
    if not isinstance(data, dict):
        return ChangeSet(), ["变更声明结构错误，已忽略"]
    out = ChangeSet()
    for field, model in (("new_entities", NewEntity), ("state_changes", StateChange), ("foreshadow", ForeshadowAction)):
        items = data.get(field) or []
        if not isinstance(items, list):
            warnings.append(f"{field} 不是数组，已忽略")
            continue
        for i, item in enumerate(items):
            try:
                getattr(out, field).append(model.model_validate(item))
            except ValidationError as e:
                warnings.append(f"{field}[{i}] 校验失败，已丢弃：{e.errors()[0].get('msg', '')}")
    return out, warnings


def check_against_ledger(
    cs: ChangeSet,
    known_names: set[str],
    open_foreshadows: dict[int, str],
) -> tuple[ChangeSet, list[str]]:
    """对照底账：
    - new_entities 中已登记的名字去重（不重复登记）；
    - state_changes 引用未登记实体 → 警告（若同一批 new_entities 中有则放行）；
    - foreshadow advance/resolve 的 id 不在未回收列表 → 尝试按描述匹配，否则丢弃并警告。
    """
    warnings: list[str] = []
    new_names = set()
    ents: list[NewEntity] = []
    for e in cs.new_entities:
        if e.name in known_names or e.name in new_names:
            continue
        new_names.add(e.name)
        ents.append(e)
    scs: list[StateChange] = []
    for sc in cs.state_changes:
        if sc.entity not in known_names and sc.entity not in new_names:
            warnings.append(f"状态变化引用了未登记实体「{sc.entity}」，已登记为待确认角色")
            ents.append(NewEntity(type="character", name=sc.entity, summary="（由状态变化自动登记，待作者确认）"))
            new_names.add(sc.entity)
        scs.append(sc)
    fos: list[ForeshadowAction] = []
    for f in cs.foreshadow:
        if f.action == "plant":
            if f.desc.strip():
                fos.append(f)
            continue
        if f.id is not None and f.id in open_foreshadows:
            fos.append(f)
            continue
        match = match_foreshadow(f.desc, open_foreshadows)
        if match is not None:
            fos.append(ForeshadowAction(action=f.action, id=match, desc=f.desc))
        else:
            warnings.append(f"伏笔动作 {f.action}「{f.desc}」找不到对应的未回收伏笔，已忽略")
    return ChangeSet(new_entities=ents, state_changes=scs, foreshadow=fos), warnings


def match_foreshadow(desc: str, open_foreshadows: dict[int, str]) -> int | None:
    d = desc.strip()
    if not d:
        return None
    for fid, fdesc in open_foreshadows.items():
        if d == fdesc or d in fdesc or fdesc in d:
            return fid
    return None

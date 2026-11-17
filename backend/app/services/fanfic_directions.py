"""v0.10 同人：创作方向模板、遵循度三档、版权声明（纯常量，无依赖）。"""

from __future__ import annotations

import re
from typing import Any

COPYRIGHT_NOTICE = (
    "同人创作仅供个人创作与学习交流使用。原著资料只能来自你有权使用的文本；本工具不保存原文，只保存提炼出的设定卡与无法还原原文的指纹。"
    "对外发布前，请遵守发布平台的同人创作规则，并自行确认原著的授权范围；未经原著版权方授权，不得用于任何商业用途。"
)

FIDELITY: dict[str, dict[str, Any]] = {
    "strict": {
        "label": "严格遵循",
        "desc": "严格遵循原著设定与时间线：人设、关系、能力体系、已发生事件都不改。",
        "rule": ("本书严格遵循原著：角色性格、说话方式、口癖、彼此关系、能力上限与原著一致；"
                 "原著时间线上已发生的事件不得改写，新情节只能填在原著留白处；不得让角色使用原著里没有的能力。"),
        "pass": 80, "factor": 1.3, "ignore": (),
    },
    "moderate": {
        "label": "有据延展",
        "desc": "可改支线与结局，人设不变：角色核心性格、说话方式、关系底色不动。",
        "rule": ("本书在原著基础上延展：可以改写支线、增加新事件、改变结局，但角色核心性格、说话方式、口癖和关系底色保持原著；"
                 "能力可以合理成长，但要有铺垫，不能凭空越级。"),
        "pass": 70, "factor": 1.0, "ignore": ("timeline",),
    },
    "loose": {
        "label": "分歧世界（AU）",
        "desc": "AU，只保留人物核心：身份、世界、时代都可以换，人物的核心性格与动机不变。",
        "rule": ("本书是 AU（平行设定）：世界观、身份、时代、能力体系都可以换，原著时间线不必遵守；"
                 "只要求保留每个角色的核心性格、动机和说话的味道，让读者一眼认得出是这个人。"),
        "pass": 55, "factor": 0.7, "ignore": ("timeline", "ability", "relation"),
    },
}
FIDELITIES = tuple(FIDELITY)

# 12 种方向：id / label / desc / tips（写作要点）/ risks（风险）/ suggested_fidelity / template（填进想法框的结构化提示）
DIRECTIONS: list[dict[str, Any]] = [
    {"id": "canon_fill", "label": "原著向补完", "suggested_fidelity": "strict",
     "desc": "在原著时间线的留白里补写：没写到的日常、幕后、视角之外的事。",
     "tips": ["先在时间线上标出要补的空档，前后两端都要和原著对得上", "角色此时知道什么、不知道什么，以原著那个时间点为准", "补完的事件不能改变原著后续的走向"],
     "risks": ["和原著后文矛盾", "写成原著情节复述，二创价值低、重合度高"],
     "template": "补写原著中「（哪段时间/哪件事）」的留白。想补的内容：；涉及角色："},
    {"id": "if_line", "label": "if 线改写", "suggested_fidelity": "moderate",
     "desc": "从原著某个关键节点分岔：如果当时做了另一个选择，之后会怎样。",
     "tips": ["分岔点只改一处，其余设定保持原著", "分岔后的连锁反应要符合各角色原有性格", "尽早让读者看到“和原著不一样了”"],
     "risks": ["分岔后人物行为失去原著动机", "改动过多变成另一个故事"],
     "template": "分岔点：原著「（事件）」时，如果「（另一个选择）」。想看到的走向："},
    {"id": "transmigration", "label": "穿书", "suggested_fidelity": "moderate",
     "desc": "现代人穿进原著世界，带着剧情先知进入故事，和原著角色发生联系后改变剧情。",
     "tips": ["穿越者的身份决定切入点：主角身边人、炮灰、反派阵营", "剧情先知要有失效的时刻，否则没有悬念", "原著角色对穿越者的反应要符合其原有性格"],
     "risks": ["原著角色沦为穿越者的工具人（集体 OOC）", "穿越者过强导致冲突消失"],
     "template": "穿越者身份（可不填）：；穿进原著的时间点：；想重点接触的角色或剧情："},
    {"id": "rebirth", "label": "重生", "suggested_fidelity": "moderate",
     "desc": "原著角色带着前世（原著结局）的记忆回到过去，弥补遗憾或改写命运。",
     "tips": ["重生者性格要在原著基础上体现“经历过结局”的变化，但核心不变", "其他角色不知道未来，言行仍按原著", "写清楚重生者最想改变的那一件事"],
     "risks": ["重生者性格大变被读者认为 OOC", "复仇线写成单调打脸"],
     "template": "重生的角色：；重生回到的时间点：；最想改变的事："},
    {"id": "system", "label": "系统", "suggested_fidelity": "moderate",
     "desc": "给原著角色或穿越者绑定系统，用任务与奖励推动在原著世界里的行动。",
     "tips": ["系统规则要和原著能力体系兼容，奖励不要直接越过原著战力上限", "任务最好围绕原著名场面设计，制造“改写名场面”的爽点", "系统要有上限和成长路线：每次升级解锁什么写清楚，不靠自残式代价制造紧张"],
     "risks": ["战力崩坏", "系统喧宾夺主，原著角色失去存在感"],
     "template": "绑定系统的角色：；系统类型与核心规则：；第一个任务想放在哪段剧情："},
    {"id": "au_modern", "label": "AU 现代", "suggested_fidelity": "loose",
     "desc": "把原著角色放进现代都市：校园、职场、娱乐圈等，身份全换，人物核心不变。",
     "tips": ["给每个主要角色找一个与原著身份气质对应的现代身份", "原著关系映射到现代（宿敌→商业对手等）", "保留口癖和说话味道是读者认人的关键"],
     "risks": ["只剩名字，人物完全变成另一个人", "现代设定与角色气质违和"],
     "template": "现代背景（校园/职场/娱乐圈/…）：；主要角色的现代身份："},
    {"id": "au_ancient", "label": "AU 古代", "suggested_fidelity": "loose",
     "desc": "把原著角色放进古代或架空王朝：宫廷、江湖、宅斗等，身份重设，核心性格保留。",
     "tips": ["先定朝代/架空程度，统一称谓和礼制", "原著能力可转为武功、权谋或技艺", "说话方式要古风化，但保留角色原有的语气特点"],
     "risks": ["古风腔压掉角色个性", "称谓礼制前后不一致"],
     "template": "古代背景（宫廷/江湖/宅斗/…）：；主要角色的古代身份："},
    {"id": "side_pov", "label": "配角主视角", "suggested_fidelity": "strict",
     "desc": "以原著配角为主角，重看原著故事或写他的独立经历。",
     "tips": ["配角视角下只能知道他在场或听说的事", "原著主角在配角眼里会呈现不同侧面，但言行不能变", "给配角一个独立的目标线"],
     "risks": ["配角被强行拔高、抢原著主角的功劳", "视角越界知道不该知道的事"],
     "template": "作为主视角的配角：；想讲他的哪段经历："},
    {"id": "cp", "label": "CP 向", "suggested_fidelity": "moderate",
     "desc": "围绕一对角色的感情线展开，可以是原著官配，也可以是读者向的配对。",
     "tips": ["感情推进要符合两人原有性格和相处模式", "用原著里的互动细节做感情起点", "感情线之外保留一条事件线，避免只剩撒糖"],
     "risks": ["为了配对改性格（最常见的 OOC）", "拉踩其他角色引发读者反感"],
     "template": "CP：「A」×「B」；感情起点（原著某件事/新事件）：；想要的感情基调："},
    {"id": "villain_redemption", "label": "反派洗白", "suggested_fidelity": "moderate",
     "desc": "给原著反派补动机、改命运，让读者重新理解他。",
     "tips": ["洗白靠补充动机和揭示隐情，而不是否认他做过的事", "反派的手段和气场要保持，不能洗成软柿子", "给受害者一方合理的反应"],
     "risks": ["洗白过度，变成为恶行开脱", "反派人设崩成正派"],
     "template": "要洗白的反派：；想揭示的隐情或动机：；他最终的结局："},
    {"id": "epilogue", "label": "后日谈", "suggested_fidelity": "strict",
     "desc": "原著完结之后的故事：角色们的后续生活、新的事件、下一代。",
     "tips": ["从原著结局的状态出发，人物关系以结局为准", "成长和变化要有原著经历做依据", "可以给原著留下的伏笔一个交代"],
     "risks": ["与原著结局设定冲突", "缺乏冲突写成流水账"],
     "template": "后日谈时间点（结局后多久）：；想写的事件或角色："},
    {"id": "crossover", "label": "跨作品联动", "suggested_fidelity": "moderate",
     "desc": "两部或多部作品的角色与世界相遇（主原著 + 联动原著）。",
     "tips": ["先定主世界和来客世界，力量体系要统一换算", "每部作品的角色都按各自原著卡把关，不要互相同化", "联动的理由要在开篇讲清楚"],
     "risks": ["战力换算失衡", "一方角色沦为背景板"],
     "template": "联动的作品（主原著之外，用 extra_source_ids 关联）：；相遇方式：；想看的角色互动："},
    {"id": "multi_transmigration", "label": "多本穿越", "suggested_fidelity": "moderate",
     "desc": "主角在多部作品的世界之间穿梭，每个世界完成目标后进入下一个。",
     "tips": ["每个世界一卷，开卷先交代这个世界的规则和主角的新身份", "主角在世界之间能带走什么、带不走什么要定死", "每个世界都要有一个只属于这个世界的名场面"],
     "risks": ["世界切换太快，读者记不住人", "能力层层叠加后失控"],
     "template": "要穿的作品（按顺序）：；每个世界的目标：；能带走的东西："},
    {"id": "reverse_transmigration", "label": "反向穿越", "suggested_fidelity": "moderate",
     "desc": "原著角色穿到现实世界或作者的世界，用原著里的本事在新世界生活。",
     "tips": ["写清他刚落地时最不适应的三件事", "原著能力在新世界打几折要定下来", "让他的原著性格和现代生活产生反差笑点或冲突"],
     "risks": ["变成单纯的现代生活流，原著味消失", "能力在现实里过强，冲突没了"],
     "template": "穿过来的角色：；落地的地方和身份：；他想在这里做成的事："},
    {"id": "revival", "label": "角色复活", "suggested_fidelity": "moderate",
     "desc": "原著里死去的角色活了下来，或在之后被救回，故事从他的存活开始改写。",
     "tips": ["复活的理由要在原著规则里站得住", "他活着会改变哪些原著事件，列出第一张多米诺骨牌", "其他角色见到他的反应按各自原著性格写"],
     "risks": ["复活理由牵强", "原著主角的成长被削弱"],
     "template": "复活的角色：；复活的方式和时间点：；他活下来后最先改变的事："},
    {"id": "unfinished", "label": "烂尾续写", "suggested_fidelity": "strict",
     "desc": "原著烂尾或断更，接着原著最后一章往下写，给读者一个像样的结局。",
     "tips": ["先把原著留下的伏笔和未解之谜列全，续写按重要度回收", "文风和节奏贴近原著后期，不要突然换腔调", "结局要回应原著开篇的核心承诺"],
     "risks": ["和原著已写内容矛盾", "急着收尾，伏笔回收草率"],
     "template": "从原著哪里接：；最想回收的伏笔：；想要的结局："},
]
def _slots(template: str) -> list[dict[str, Any]]:
    """把模板「标签：；标签：」拆成可填的空位（全部可不填）。"""
    out = []
    for i, seg in enumerate(x for x in template.split("；") if x.strip()):
        label = seg.split("：")[0].strip()
        if not label:
            continue
        ph = ""
        m = re.search(r"[（(]([^）)]+)[）)]", label)
        if m:
            ph = m.group(1)
            label = re.sub(r"[（(][^）)]+[）)]", "", label).strip() or label
        out.append({"key": f"s{i}", "label": label[:30], "placeholder": ph[:40], "optional": True})
    return out


for _d in DIRECTIONS:
    _d["slots"] = _slots(_d["template"])

DIRECTION_IDS = tuple(d["id"] for d in DIRECTIONS)
DIRECTION_BY_ID = {d["id"]: d for d in DIRECTIONS}


POVS: dict[str, dict[str, str]] = {
    "first": {"label": "第一人称主角", "rule": "第一人称，只写主角看到、听到、想到的。"},
    "third_limited": {"label": "第三人称主角限知", "rule": "第三人称，镜头跟着主角，只写主角知道的事。"},
    "third_multi": {"label": "第三人称多视角", "rule": "第三人称，可在不同场景切换视角人物，一个场景只跟一个人。"},
    "canon_pov": {"label": "原著角色视角", "rule": "从原著角色的眼睛看主角和事件，原著角色的认知以原著那个时间点为准。"},
    "omniscient": {"label": "全知视角", "rule": "全知视角，可交代多方动机，但关键反转前不剧透。"},
}
OC_TYPES = {"transmigrator": "穿越者", "native": "原住民原创角色", "soul_swap": "魂穿原著角色"}


def catalog() -> dict[str, Any]:
    return {
        "directions": DIRECTIONS,
        "povs": [{"id": k, "label": v["label"]} for k, v in POVS.items()],
        "oc_types": [{"id": k, "label": v} for k, v in OC_TYPES.items()],
        "fidelities": [{"id": k, "label": v["label"], "desc": v["desc"], "pass_score": v["pass"]} for k, v in FIDELITY.items()],
        "copyright_notice": COPYRIGHT_NOTICE,
    }

/** v0.11.1 热门同人题材模板（mock 用；由 backend/app/services/fanfic_templates.py 导出，保持一致） */
import type { FanficTemplate, FanficTemplateCategory } from '@/lib/types'

export const FF_TEMPLATE_CATEGORIES: FanficTemplateCategory[] = ["国漫", "网文", "欧美", "日漫", "游戏"]

export const FF_TEMPLATES: FanficTemplate[] = [
 {
  "id": "douluo",
  "title": "斗罗大陆",
  "aliases": [
   "斗罗",
   "绝世唐门（续作）"
  ],
  "category": "网文",
  "intro": "以武魂觉醒和魂环猎取为核心的魂师成长故事，学院群像与神位传承并行。",
  "characters": [
   "唐三",
   "小舞",
   "戴沐白",
   "朱竹清",
   "马红俊",
   "宁荣荣",
   "奥斯卡",
   "玉小刚",
   "比比东",
   "千仞雪",
   "唐昊"
  ],
  "search_focus": [
   "武魂分类与魂环年限颜色对应",
   "魂师等级从魂士到封号斗罗及神级",
   "史莱克七怪各自武魂与魂技",
   "武魂殿与天斗、星罗两大帝国的关系",
   "海神与修罗神神位传承"
  ],
  "styles": [
   {
    "label": "穿越成史莱克同学",
    "desc": "以史莱克学院同期生身份入局，跟着七怪一起猎魂环、参加大赛",
    "direction": "transmigration"
   },
   {
    "label": "魂环/魂骨签到系统",
    "desc": "带签到或抽奖系统，按年限获得魂环魂骨，节奏靠系统任务推进",
    "direction": "system"
   },
   {
    "label": "双生/自创武魂",
    "desc": "主角拥有原著体系内合理推演的特殊武魂，重点写魂技搭配",
    "direction": "if_line"
   },
   {
    "label": "武魂殿线洗白",
    "desc": "从比比东或千仞雪视角重写武魂殿立场，给反派动机补全",
    "direction": "villain_redemption"
   },
   {
    "label": "斗罗诸天联动",
    "desc": "多部斗罗或其他作品世界串联，按世界切换副本",
    "direction": "crossover"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "villain_redemption",
   "if_line",
   "cp"
  ]
 },
 {
  "id": "doupo",
  "title": "斗破苍穹",
  "aliases": [
   "斗破"
  ],
  "category": "网文",
  "intro": "落魄少年借戒中老者之力重修斗气、收集异火，一路从小镇打上中州。",
  "characters": [
   "萧炎",
   "药尘",
   "萧薰儿",
   "美杜莎",
   "纳兰嫣然",
   "云韵",
   "小医仙",
   "萧战",
   "魂天帝"
  ],
  "search_focus": [
   "斗气等级从斗之气到斗帝",
   "异火榜排名与特性",
   "炼药师品阶与丹药",
   "加玛帝国、迦南学院与中州势力分布",
   "魂殿与古族、魂族的关系"
  ],
  "styles": [
   {
    "label": "穿越成萧家族人",
    "desc": "以萧家旁系或萧炎兄弟身份见证退婚到崛起的全过程",
    "direction": "transmigration"
   },
   {
    "label": "异火收集系统",
    "desc": "绑定收集异火或炼药系统，用任务推动探索各大秘境",
    "direction": "system"
   },
   {
    "label": "退婚线改写",
    "desc": "从纳兰嫣然或云岚宗视角改写三年之约，给配角更完整的成长线",
    "direction": "if_line"
   },
   {
    "label": "云韵 / 美杜莎 CP 向",
    "desc": "围绕主角与某位女主的感情线细写，日常与并肩作战交替",
    "direction": "cp"
   },
   {
    "label": "魂殿反派视角",
    "desc": "以魂殿成员视角写大陆暗面，讲反派的立场与挣扎",
    "direction": "side_pov"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "if_line",
   "cp",
   "side_pov"
  ]
 },
 {
  "id": "marvel",
  "title": "漫威",
  "aliases": [
   "MCU",
   "漫威宇宙",
   "复仇者联盟"
  ],
  "category": "欧美",
  "intro": "超级英雄共享宇宙：科技、魔法、变种与宇宙势力交错，围绕无限宝石展开多阶段故事。",
  "characters": [
   "托尼·斯塔克",
   "史蒂夫·罗杰斯",
   "索尔",
   "洛基",
   "娜塔莎·罗曼诺夫",
   "彼得·帕克",
   "布鲁斯·班纳",
   "斯蒂芬·斯特兰奇",
   "灭霸"
  ],
  "search_focus": [
   "MCU 各阶段电影时间线",
   "六颗无限宝石的能力与下落",
   "神盾局与九头蛇的关系",
   "复仇者联盟成员与能力上限",
   "多元宇宙与时间线分支设定"
  ],
  "styles": [
   {
    "label": "穿越成神盾局特工",
    "desc": "以特工或斯塔克工业员工身份切入，见证复仇者组建",
    "direction": "transmigration"
   },
   {
    "label": "美漫签到系统",
    "desc": "在关键事件节点签到获取能力或科技，逐步卷入主线",
    "direction": "system"
   },
   {
    "label": "平行宇宙",
    "desc": "在多元宇宙里设定一条分岔时间线，人物身份与结局改变",
    "direction": "if_line"
   },
   {
    "label": "洛基洗白",
    "desc": "补写洛基的动机与成长，让反派走向救赎",
    "direction": "villain_redemption"
   },
   {
    "label": "漫威 × DC 联动",
    "desc": "两大宇宙角色相遇，写阵营碰撞与合作",
    "direction": "crossover"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "if_line",
   "villain_redemption",
   "crossover"
  ]
 },
 {
  "id": "longzu",
  "title": "龙族",
  "aliases": [
   "龙族系列"
  ],
  "category": "网文",
  "intro": "衰小孩被神秘学院录取，卷入混血种与龙王之间的千年战争，青春与宿命并行。",
  "characters": [
   "路明非",
   "楚子航",
   "恺撒·加图索",
   "陈墨瞳",
   "芬格尔",
   "路鸣泽",
   "昂热",
   "绘梨衣",
   "夏弥"
  ],
  "search_focus": [
   "混血种血统等级与龙化风险",
   "言灵序列表与代表言灵",
   "卡塞尔学院执行部与秘党",
   "四大君主与龙王名单",
   "加图索家族与蛇岐八家"
  ],
  "styles": [
   {
    "label": "穿越成卡塞尔新生",
    "desc": "以同届新生身份参加 3E 考试和自由一日，和学生会/狮心会打交道",
    "direction": "transmigration"
   },
   {
    "label": "拯救绘梨衣",
    "desc": "从东京篇关键节点分岔，改写悲剧结局",
    "direction": "if_line"
   },
   {
    "label": "言灵觉醒系统",
    "desc": "主角通过系统解锁言灵序列，重点写言灵搭配与代价",
    "direction": "system"
   },
   {
    "label": "楚子航视角",
    "desc": "以师兄视角补完他的过去与执行部任务",
    "direction": "side_pov"
   },
   {
    "label": "龙王视角",
    "desc": "以某位龙王的立场重述人与龙的战争",
    "direction": "villain_redemption"
   }
  ],
  "directions": [
   "transmigration",
   "if_line",
   "system",
   "side_pov",
   "cp"
  ]
 },
 {
  "id": "pokemon",
  "title": "宝可梦",
  "aliases": [
   "精灵宝可梦",
   "神奇宝贝",
   "口袋妖怪"
  ],
  "category": "游戏",
  "intro": "训练家与宝可梦结伴旅行、挑战道馆与联盟，在各地区遇见传说与幻之宝可梦。",
  "characters": [
   "小智",
   "皮卡丘",
   "小霞",
   "小刚",
   "小茂",
   "武藏",
   "小次郎",
   "喵喵",
   "大木博士",
   "超梦"
  ],
  "search_focus": [
   "宝可梦属性相克表",
   "各地区道馆与联盟冠军",
   "进化方式分类",
   "传说与幻之宝可梦设定",
   "训练家对战与持有规则"
  ],
  "styles": [
   {
    "label": "穿越成新人训练家",
    "desc": "从选择御三家开始，按地区道馆路线旅行",
    "direction": "transmigration"
   },
   {
    "label": "图鉴签到系统",
    "desc": "收服或遇见新宝可梦时获得奖励，系统推动收集与培育",
    "direction": "system"
   },
   {
    "label": "宝可梦降临现实",
    "desc": "宝可梦出现在现代都市，写普通人与宝可梦的共生",
    "direction": "au_modern"
   },
   {
    "label": "研究员 / 饲育家路线",
    "desc": "不走联盟对战，专注研究、饲育或协调训练家",
    "direction": "side_pov"
   },
   {
    "label": "火箭队视角",
    "desc": "以反派组织成员视角写另一面的冒险",
    "direction": "villain_redemption"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "au_modern",
   "side_pov",
   "canon_fill"
  ]
 },
 {
  "id": "naruto",
  "title": "火影忍者",
  "aliases": [
   "火影",
   "NARUTO",
   "博人传（续作）"
  ],
  "category": "日漫",
  "intro": "被村子排斥的少年立志成为火影，忍者世界的羁绊、仇恨与战争轮回贯穿始终。",
  "characters": [
   "漩涡鸣人",
   "宇智波佐助",
   "春野樱",
   "旗木卡卡西",
   "宇智波鼬",
   "自来也",
   "纲手",
   "大蛇丸",
   "宇智波斑",
   "日向雏田",
   "我爱罗"
  ],
  "search_focus": [
   "查克拉性质变化与五大属性",
   "忍者等级与五大国忍村",
   "晓组织成员与能力",
   "写轮眼等血继限界与瞳术",
   "尾兽与人柱力",
   "第四次忍界大战经过"
  ],
  "styles": [
   {
    "label": "穿越宇智波族人",
    "desc": "在灭族之夜前穿越，尝试改变宇智波命运",
    "direction": "transmigration"
   },
   {
    "label": "忍术签到 / 抽奖系统",
    "desc": "通过系统获得忍术或血继，逐步成长为强者",
    "direction": "system"
   },
   {
    "label": "鼬 / 止水线",
    "desc": "补写鼬与止水的选择与牺牲，给反派化角色正名",
    "direction": "villain_redemption"
   },
   {
    "label": "晓组织视角",
    "desc": "以晓成员视角写组织内部的日常与理想",
    "direction": "side_pov"
   },
   {
    "label": "和平年代后传",
    "desc": "写战后新一代忍者或火影们的日常",
    "direction": "epilogue"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "villain_redemption",
   "if_line",
   "side_pov"
  ]
 },
 {
  "id": "onepiece",
  "title": "海贼王",
  "aliases": [
   "航海王",
   "ONE PIECE"
  ],
  "category": "日漫",
  "intro": "橡胶人少年组建草帽海贼团，在伟大航路追寻传说中的大秘宝与世界真相。",
  "characters": [
   "蒙奇·D·路飞",
   "罗罗诺亚·索隆",
   "娜美",
   "山治",
   "乌索普",
   "托尼托尼·乔巴",
   "妮可·罗宾",
   "波特卡斯·D·艾斯",
   "香克斯",
   "特拉法尔加·罗",
   "爱德华·纽盖特"
  ],
  "search_focus": [
   "恶魔果实三大类与觉醒",
   "霸气三种类型",
   "四皇、七武海与海军三大将",
   "伟大航路与新世界地理",
   "空白的一百年与世界政府"
  ],
  "styles": [
   {
    "label": "穿越成海贼新人",
    "desc": "吃下某颗果实出海，组建自己的海贼团",
    "direction": "transmigration"
   },
   {
    "label": "海军视角",
    "desc": "以海军成员身份看待海贼时代，写正义的不同理解",
    "direction": "side_pov"
   },
   {
    "label": "拯救艾斯",
    "desc": "从顶上战争前分岔，改写关键结局",
    "direction": "if_line"
   },
   {
    "label": "加入草帽团",
    "desc": "作为新船员加入草帽团，补写航行中的日常",
    "direction": "canon_fill"
   },
   {
    "label": "果实能力系统",
    "desc": "系统帮助开发果实能力，写能力的成长与限制",
    "direction": "system"
   }
  ],
  "directions": [
   "transmigration",
   "side_pov",
   "if_line",
   "canon_fill",
   "system"
  ]
 },
 {
  "id": "harrypotter",
  "title": "哈利·波特",
  "aliases": [
   "HP",
   "哈利波特"
  ],
  "category": "欧美",
  "intro": "魔法学校七年成长史，少年巫师与黑魔王之间的宿命对决。",
  "characters": [
   "哈利·波特",
   "赫敏·格兰杰",
   "罗恩·韦斯莱",
   "阿不思·邓布利多",
   "西弗勒斯·斯内普",
   "伏地魔",
   "德拉科·马尔福",
   "小天狼星布莱克",
   "卢娜·洛夫古德"
  ],
  "search_focus": [
   "霍格沃茨四大学院与特点",
   "魔杖与魔咒规则",
   "魂器设定",
   "魔法部与巫师法律",
   "各学年主线事件时间线"
  ],
  "styles": [
   {
    "label": "同届穿越学生",
    "desc": "以同届新生身份入学分院，跟着七年主线成长",
    "direction": "transmigration"
   },
   {
    "label": "斯莱特林线",
    "desc": "以斯莱特林学生视角写学院与纯血家族",
    "direction": "side_pov"
   },
   {
    "label": "掠夺者时代",
    "desc": "回到上一代写掠夺者们的学生时代",
    "direction": "canon_fill"
   },
   {
    "label": "拯救小天狼星",
    "desc": "从关键事件分岔，保住重要角色",
    "direction": "if_line"
   },
   {
    "label": "德拉科洗白",
    "desc": "补写马尔福家族的挣扎，让角色走向转变",
    "direction": "villain_redemption"
   }
  ],
  "directions": [
   "transmigration",
   "side_pov",
   "canon_fill",
   "if_line",
   "villain_redemption"
  ]
 },
 {
  "id": "genshin",
  "title": "原神",
  "aliases": [
   "Genshin Impact"
  ],
  "category": "游戏",
  "intro": "异世旅行者寻找血亲，在提瓦特七国与各地神明、执行官结下羁绊。",
  "characters": [
   "旅行者",
   "派蒙",
   "钟离",
   "温迪",
   "雷电将军",
   "纳西妲",
   "芙宁娜",
   "胡桃",
   "达达利亚",
   "魈"
  ],
  "search_focus": [
   "提瓦特七国与七神",
   "神之眼与七种元素",
   "愚人众执行官名单",
   "深渊教团与坎瑞亚",
   "各国魔神任务主线"
  ],
  "styles": [
   {
    "label": "穿越成提瓦特原住民",
    "desc": "以某国居民或冒险家协会成员身份入局",
    "direction": "transmigration"
   },
   {
    "label": "团宠旅行者",
    "desc": "旅行者被各国角色照顾和争抢，以日常甜文为主",
    "direction": "cp"
   },
   {
    "label": "执行官视角",
    "desc": "以愚人众执行官视角写至冬的谋划",
    "direction": "side_pov"
   },
   {
    "label": "现代 AU",
    "desc": "把角色搬进现代都市校园或职场",
    "direction": "au_modern"
   },
   {
    "label": "魔神战争补完",
    "desc": "补写主线之前的魔神战争或坎瑞亚往事",
    "direction": "canon_fill"
   }
  ],
  "directions": [
   "transmigration",
   "cp",
   "side_pov",
   "au_modern",
   "canon_fill"
  ]
 },
 {
  "id": "starrail",
  "title": "崩坏：星穹铁道",
  "aliases": [
   "星铁",
   "星穹铁道"
  ],
  "category": "游戏",
  "intro": "开拓者搭乘星穹列车穿行群星，在各个世界卷入星神与命途的纷争。",
  "characters": [
   "开拓者",
   "三月七",
   "丹恒",
   "姬子",
   "瓦尔特·杨",
   "卡芙卡",
   "银狼",
   "刃",
   "景元",
   "流萤",
   "黄泉"
  ],
  "search_focus": [
   "星神与命途体系",
   "星穹列车与开拓意义",
   "星核猎手成员与艾利欧剧本",
   "仙舟罗浮与匹诺康尼主线",
   "反物质军团与绝灭大君"
  ],
  "styles": [
   {
    "label": "穿越成列车组成员",
    "desc": "以新乘客身份登上列车，跟着开拓主线跑图",
    "direction": "transmigration"
   },
   {
    "label": "命途令使系统",
    "desc": "系统引导主角踏上某条命途，写力量与代价",
    "direction": "system"
   },
   {
    "label": "星核猎手视角",
    "desc": "以猎手成员视角看剧本推进",
    "direction": "side_pov"
   },
   {
    "label": "列车团宠",
    "desc": "列车组日常与互动为主的轻松向",
    "direction": "cp"
   },
   {
    "label": "崩坏系列联动",
    "desc": "与同公司其他作品角色互动",
    "direction": "crossover"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "side_pov",
   "cp",
   "crossover"
  ]
 },
 {
  "id": "fanren",
  "title": "凡人修仙传",
  "aliases": [
   "凡人"
  ],
  "category": "网文",
  "intro": "资质平庸的山村少年凭谨慎与奇遇一步步修仙，从人界走向灵界与仙界。",
  "characters": [
   "韩立",
   "南宫婉",
   "厉飞雨",
   "墨大夫",
   "银月",
   "紫灵",
   "大衍神君",
   "元瑶"
  ],
  "search_focus": [
   "修仙境界从炼气到大乘渡劫",
   "掌天瓶（小绿瓶）的作用",
   "人界、灵界、仙界划分",
   "七玄门、黄枫谷与越国修仙界",
   "法宝、符箓与丹药体系"
  ],
  "styles": [
   {
    "label": "穿越成韩立同门",
    "desc": "以七玄门或黄枫谷同门身份经历早期修仙",
    "direction": "transmigration"
   },
   {
    "label": "苟道稳健流",
    "desc": "主角延续谨慎风格，用系统或金手指稳扎稳打",
    "direction": "system"
   },
   {
    "label": "南宫婉线日常",
    "desc": "补写主角与道侣的相处与重逢",
    "direction": "cp"
   },
   {
    "label": "灵界续写",
    "desc": "在原著后期地图里写新人物的修行",
    "direction": "epilogue"
   },
   {
    "label": "配角视角",
    "desc": "以厉飞雨等凡人配角视角看修仙世界",
    "direction": "side_pov"
   }
  ],
  "directions": [
   "transmigration",
   "system",
   "cp",
   "side_pov",
   "canon_fill"
  ]
 },
 {
  "id": "guimi",
  "title": "诡秘之主",
  "aliases": [
   "诡秘"
  ],
  "category": "网文",
  "intro": "蒸汽与机械时代的克苏鲁式奇幻，穿越者伪装成神秘存在，在序列途径中步步登神。",
  "characters": [
   "克莱恩·莫雷蒂",
   "奥黛丽·霍尔",
   "阿尔杰·威尔逊",
   "戴里克·伯格",
   "伦纳德·米切尔",
   "阿蒙",
   "邓恩·史密斯",
   "佛尔思·沃尔"
  ],
  "search_focus": [
   "22 条神之途径与序列名称",
   "魔药与扮演法",
   "塔罗会成员与代号",
   "鲁恩王国、廷根与贝克兰德",
   "旧日、外神与真神设定"
  ],
  "styles": [
   {
    "label": "另一途径非凡者",
    "desc": "穿越成其他途径的非凡者，写不同序列的成长与失控风险",
    "direction": "transmigration"
   },
   {
    "label": "塔罗会新成员",
    "desc": "以新加入的塔罗会成员身份参与聚会与任务",
    "direction": "canon_fill"
   },
   {
    "label": "值夜者日常",
    "desc": "补写廷根值夜者小队的日常与案件",
    "direction": "canon_fill"
   },
   {
    "label": "阿蒙视角",
    "desc": "以反派视角写偷盗与寄生的另一种逻辑",
    "direction": "villain_redemption"
   },
   {
    "label": "后续纪元",
    "desc": "写原著故事之后的世界与新一代非凡者",
    "direction": "epilogue"
   }
  ],
  "directions": [
   "transmigration",
   "canon_fill",
   "villain_redemption",
   "side_pov",
   "epilogue"
  ]
 },
 {
  "id": "conan",
  "title": "名侦探柯南",
  "aliases": [
   "柯南"
  ],
  "category": "日漫",
  "intro": "被灌下药物变小的高中生侦探，一边破案一边追查神秘黑衣组织。",
  "characters": [
   "江户川柯南",
   "工藤新一",
   "毛利兰",
   "毛利小五郎",
   "灰原哀",
   "服部平次",
   "怪盗基德",
   "琴酒",
   "安室透",
   "赤井秀一"
  ],
  "search_focus": [
   "黑衣组织成员代号",
   "APTX4869 设定",
   "主线剧情关键案件时间线",
   "公安、FBI 与 CIA 卧底",
   "少年侦探团成员"
  ],
  "styles": [
   {
    "label": "穿越成组织卧底",
    "desc": "以组织成员或卧底身份周旋于多方之间",
    "direction": "transmigration"
   },
   {
    "label": "警校组拯救",
    "desc": "从关键事件分岔，改变警校组成员的命运",
    "direction": "if_line"
   },
   {
    "label": "推理系统",
    "desc": "绑定破案系统，靠推理获得奖励",
    "direction": "system"
   },
   {
    "label": "灰原线",
    "desc": "以灰原哀视角补写她的过去与现在",
    "direction": "side_pov"
   },
   {
    "label": "安室透 / 赤井 CP 向",
    "desc": "围绕人气角色写感情与搭档关系",
    "direction": "cp"
   }
  ],
  "directions": [
   "transmigration",
   "if_line",
   "system",
   "side_pov",
   "cp"
  ]
 },
 {
  "id": "zhetian",
  "title": "遮天",
  "aliases": [],
  "category": "网文",
  "intro": "九龙拉棺把一群同学带离地球，主角在荒古体质与帝路争锋中走向成帝。",
  "characters": [
   "叶凡",
   "庞博",
   "黑皇",
   "姬紫月",
   "段德",
   "安妙依",
   "狠人大帝",
   "无始大帝"
  ],
  "search_focus": [
   "修炼秘境轮海、道宫、四极、化龙、仙台",
   "九龙拉棺事件",
   "生命禁区与至尊",
   "古皇与大帝名单",
   "北斗星域与东荒势力"
  ],
  "styles": [
   {
    "label": "九龙拉棺同行者",
    "desc": "作为同一批被带走的同学之一，走出另一条成长线",
    "direction": "transmigration"
   },
   {
    "label": "禁区至尊视角",
    "desc": "以禁区存在的立场写黑暗动乱的缘由",
    "direction": "side_pov"
   },
   {
    "label": "狠人线补完",
    "desc": "补写某位古代大帝的过往",
    "direction": "canon_fill"
   },
   {
    "label": "辰东宇宙联动",
    "desc": "与同作者其他作品世界串联",
    "direction": "crossover"
   },
   {
    "label": "帝路签到",
    "desc": "带系统在帝路争锋中逆袭",
    "direction": "system"
   }
  ],
  "directions": [
   "transmigration",
   "side_pov",
   "canon_fill",
   "crossover",
   "system"
  ]
 },
 {
  "id": "wanmei",
  "title": "完美世界",
  "aliases": [],
  "category": "网文",
  "intro": "大荒小村走出的少年，历经至尊骨被夺与重修，最终镇守帝关成就荒天帝。",
  "characters": [
   "石昊",
   "火灵儿",
   "云曦",
   "柳神",
   "石毅",
   "清风",
   "安澜",
   "曹雨生"
  ],
  "search_focus": [
   "修炼境界从搬血到真一与仙王",
   "至尊骨与重瞳",
   "异域与九天十地",
   "帝关与边荒之战",
   "柳神来历"
  ],
  "styles": [
   {
    "label": "穿越成石村人",
    "desc": "以石村孩子身份与主角一同长大",
    "direction": "transmigration"
   },
   {
    "label": "异域视角",
    "desc": "以异域生灵视角看帝关战争",
    "direction": "side_pov"
   },
   {
    "label": "柳神线",
    "desc": "补写柳神的过往与守护",
    "direction": "canon_fill"
   },
   {
    "label": "荒天帝后传",
    "desc": "写原著之后的世界与传人",
    "direction": "epilogue"
   },
   {
    "label": "辰东宇宙联动",
    "desc": "与同作者其他作品角色相遇",
    "direction": "crossover"
   }
  ],
  "directions": [
   "transmigration",
   "side_pov",
   "canon_fill",
   "epilogue",
   "crossover"
  ]
 },
 {
  "id": "dc",
  "title": "DC",
  "aliases": [
   "DC 宇宙",
   "正义联盟"
  ],
  "category": "欧美",
  "intro": "以哥谭和大都会为舞台的超级英雄宇宙，正义联盟与各路反派在多元宇宙中交锋。",
  "characters": [
   "布鲁斯·韦恩",
   "克拉克·肯特",
   "戴安娜",
   "小丑",
   "迪克·格雷森",
   "巴里·艾伦",
   "哈莉·奎茵",
   "莱克斯·卢瑟"
  ],
  "search_focus": [
   "正义联盟成员与能力上限",
   "蝙蝠家族与历任罗宾",
   "哥谭反派名单",
   "氪星与超人弱点",
   "多元宇宙与危机事件"
  ],
  "styles": [
   {
    "label": "穿越哥谭",
    "desc": "以哥谭普通市民或警员身份卷入蝙蝠侠故事",
    "direction": "transmigration"
   },
   {
    "label": "蝙蝠家团宠",
    "desc": "以蝙蝠家族日常互动为主的轻松向",
    "direction": "cp"
   },
   {
    "label": "反派洗白",
    "desc": "从小丑或哈莉的立场重写动机",
    "direction": "villain_redemption"
   },
   {
    "label": "平行地球",
    "desc": "在多元宇宙的另一个地球改写英雄身份",
    "direction": "au_modern"
   },
   {
    "label": "漫威 × DC 联动",
    "desc": "两大宇宙交汇的冒险",
    "direction": "crossover"
   }
  ],
  "directions": [
   "transmigration",
   "cp",
   "villain_redemption",
   "if_line",
   "crossover"
  ]
 },
 {
  "id": "yirenzhixia",
  "title": "一人之下",
  "aliases": [],
  "category": "国漫",
  "intro": "现代都市里隐藏着修炼炁的异人，主角卷入八奇技与甲申之乱的旧事。",
  "characters": [
   "张楚岚",
   "冯宝宝",
   "王也",
   "诸葛青",
   "张之维",
   "无根生",
   "夏禾"
  ],
  "search_focus": [
   "异人与炁的设定",
   "八奇技名单与来历",
   "甲申之乱经过",
   "哪都通公司与十佬",
   "天师府与全性"
  ],
  "styles": [
   {
    "label": "穿越成异人",
    "desc": "以新觉醒的异人身份加入公司或门派",
    "direction": "transmigration"
   },
   {
    "label": "甲申年代补完",
    "desc": "回到甲申之乱写三十六贼的故事",
    "direction": "canon_fill"
   },
   {
    "label": "全性视角",
    "desc": "以全性成员立场写异人界的另一面",
    "direction": "side_pov"
   },
   {
    "label": "八奇技系统",
    "desc": "系统引导主角追寻某项奇技",
    "direction": "system"
   }
  ],
  "directions": [
   "transmigration",
   "canon_fill",
   "side_pov",
   "system"
  ]
 },
 {
  "id": "jujutsu",
  "title": "咒术回战",
  "aliases": [
   "咒回"
  ],
  "category": "日漫",
  "intro": "吞下特级咒物的少年成为咒术师，与同伴对抗由负面情绪诞生的咒灵。",
  "characters": [
   "虎杖悠仁",
   "伏黑惠",
   "钉崎野蔷薇",
   "五条悟",
   "两面宿傩",
   "夏油杰",
   "七海建人"
  ],
  "search_focus": [
   "咒力、术式与领域展开",
   "咒术师与咒灵等级",
   "东京咒术高专与京都校",
   "涩谷事变经过",
   "宿傩手指与咒物"
  ],
  "styles": [
   {
    "label": "穿越成高专学生",
    "desc": "以咒术高专同届学生身份参与任务",
    "direction": "transmigration"
   },
   {
    "label": "救夏油杰 if 线",
    "desc": "从高专时期分岔，改写关键角色的选择",
    "direction": "if_line"
   },
   {
    "label": "术式开发系统",
    "desc": "系统帮助主角开发与强化术式",
    "direction": "system"
   },
   {
    "label": "咒灵视角",
    "desc": "以咒灵立场看人类与咒术界",
    "direction": "side_pov"
   }
  ],
  "directions": [
   "transmigration",
   "if_line",
   "system",
   "side_pov",
   "cp"
  ]
 }
] as FanficTemplate[]

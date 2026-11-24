"""接待机器人的评测句（docs/任务单/12_接待机器人_设计.md 第十节）：39 句模拟客人的话，带上下文和该判成哪类、这一轮该问哪件。

来源：真实聊天（PPT工厂/inbox/*/聊天记录.md）里客人的说法改写（名字、学校换掉），客户反馈里的改稿说法，问答卡的话题，
再加故意含糊的、一句两件事的。pytest（tests/intake/test_reception.py）和 scripts/reception_eval.py 共用。

字段：
- text：客人这次说的；kinds：消息类型（发文件就是 file）
- stage：visitor 没买 / collecting 收资料 / making 制作中 / delivered 交了水印版
- last_bot：助手上一句（空 = 没有）
- want：该判成的类，第一个是主的；ok：也算对的其他类（真有歧义时）
- ask：这一轮该问的那件（None = 不该问）；只在 visitor 阶段由代码直接算，认领后的要看订单状态，这里不判
- handoff：这一句该不该转负责人
"""

CASES: list[dict] = [
    # ---- 售前 ----
    {"id": "V01", "text": "小红书来的", "stage": "visitor", "want": ["greet"], "ask": "duration_papers"},
    {"id": "V02", "text": "你好，在吗", "stage": "visitor", "want": ["greet"], "ok": ["chitchat"], "ask": "duration_papers"},
    {"id": "V03", "text": "组会讲一篇文献，20分钟左右，多少钱", "stage": "visitor", "want": ["ask_price"], "ask": "present_date"},
    {"id": "V04", "text": "多少钱呀", "stage": "visitor", "want": ["ask_price"], "ask": "duration_papers"},
    {"id": "V05", "text": "开题汇报大概多少钱，下周三要，来得及吗", "stage": "visitor", "want": ["ask_price", "ask_time"],
     "ok": ["ask_time"], "ask": "duration_papers"},
    {"id": "V06", "text": "能做英文的汇报吗", "stage": "visitor", "want": ["ask_scope"], "ask": "duration_papers"},
    {"id": "V07", "text": "我是做问卷研究的，开题能做吗", "stage": "visitor", "want": ["ask_scope"], "ask": "duration_papers"},
    {"id": "V08", "text": "能帮我把问卷数据分析了再做成PPT吗", "stage": "visitor", "want": ["ask_scope"], "ok": ["special"]},
    {"id": "V09", "text": "明天下午就要汇报了，现在还来得及吗", "stage": "visitor", "want": ["ask_time"], "ask": "duration_papers"},
    {"id": "V10", "text": "能加急吗", "stage": "visitor", "want": ["ask_time"], "ask": "duration_papers"},
    {"id": "V11", "text": "有做好的样例可以先看看吗", "stage": "visitor", "want": ["ask_sample"], "ask": "duration_papers"},
    {"id": "V12", "text": "那我就买这个吧，怎么付款", "stage": "visitor", "want": ["ask_buy"]},
    {"id": "V13", "text": "你是真人还是机器人", "stage": "visitor", "want": ["ask_bot"], "ask": None},
    {"id": "V14", "text": "我要讲一个半小时，8篇文献，能做吗", "stage": "visitor", "want": ["special"], "handoff": True},
    {"id": "V15", "text": "你们收代理吗，我们工作室想合作", "stage": "visitor", "want": ["special"], "handoff": True},
    {"id": "V16", "text": "哈哈哈好的谢谢", "stage": "visitor", "want": ["chitchat"], "ask": None},
    {"id": "V17", "text": "15分钟，一篇", "stage": "visitor", "last_bot": "大概讲多久、几篇呀", "want": ["answer"],
     "ok": ["ask_price"], "ask": "present_date"},
    {"id": "V18", "text": "说了半天你听不懂吗，叫你们负责人来", "stage": "visitor", "want": ["escalate"], "handoff": True, "ask": None},
    {"id": "V19", "text": "能开发票吗，要报销", "stage": "visitor", "want": ["invoice"], "ask": None},
    {"id": "V20", "text": "能便宜点吗，学生党", "stage": "visitor", "want": ["ask_price"], "ok": ["special"]},
    # 11-19 资料清单：问要准备什么 → send_materials（不知道场合先问场合）
    {"id": "V21", "text": "下单前要准备什么资料呀", "stage": "visitor", "want": ["ask_materials"]},
    {"id": "V22", "text": "开题的话需要给你们准备什么", "stage": "visitor", "want": ["ask_materials"], "ok": ["ask_scope"]},
    # ---- 认领、收资料 ----
    {"id": "S01", "text": "PSY-AB12CD34E", "stage": "collecting", "want": ["send_code"]},
    {"id": "S02", "text": "[文件 #3 Affiliation in human-AI interactions.pdf]", "kinds": ["file"], "stage": "collecting",
     "want": ["send_material"]},
    {"id": "S03", "text": "老师要求重点讲研究设计，结果要用原文的图", "stage": "collecting", "want": ["send_material"]},
    {"id": "S04", "text": "下周三下午", "stage": "collecting", "last_bot": "你大概哪天汇报呀，人多的话我得排一下",
     "want": ["answer"], "ok": ["send_material"]},
    {"id": "S05", "text": "我是浙江师范大学的，我们组有统一的模板", "stage": "collecting", "want": ["send_material"]},
    {"id": "S06", "text": "可以不放摘要页吗", "stage": "collecting", "want": ["ask_scope"], "ok": ["send_material"]},
    {"id": "S07", "text": "还要发什么吗", "stage": "collecting", "want": ["ask_materials"], "ok": ["send_material"]},
    # ---- 制作中 ----
    {"id": "M01", "text": "ppt宝宝出生了嘛", "stage": "making", "want": ["ask_progress"]},
    {"id": "M02", "text": "还要多久呀，我有点急", "stage": "making", "want": ["ask_progress"], "ok": ["ask_time"]},
    # ---- 交了水印版 ----
    {"id": "D01", "text": "第5页的图太小了，结果那页字太多", "stage": "delivered", "want": ["revise"]},
    {"id": "D02", "text": "能把配色换成墨绿色吗", "stage": "delivered", "want": ["revise"]},
    {"id": "D03", "text": "挺好的，没问题了，谢谢", "stage": "delivered", "want": ["confirm_ok"], "ok": ["chitchat"]},
    {"id": "D04", "text": "做得不满意，我要退款", "stage": "delivered", "want": ["refund"], "handoff": True},
    {"id": "D05", "text": "我不想要了，能撤单吗", "stage": "collecting", "want": ["refund"]},
    {"id": "D06", "text": "你们这是骗人吧，我要去差评", "stage": "delivered", "want": ["escalate"], "handoff": True},
    {"id": "D07", "text": "[动画表情]", "stage": "delivered", "want": ["chitchat"]},
    {"id": "D08", "text": "是AI在回我吗", "stage": "making", "want": ["ask_bot"]},
]

STAGE_LABEL = {"visitor": "还没买（访客）", "collecting": "收资料", "making": "制作中", "delivered": "已交水印版"}


def correct(case: dict, got: list[str]) -> bool:
    """主类对上（want 的第一个，或 ok 里的）就算对。"""
    if not got:
        return False
    return got[0] in [case["want"][0], *case.get("ok", [])] or (len(case["want"]) > 1 and got[0] in case["want"])

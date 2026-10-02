"""生日关怀：今日寿星查询、设置读写、每日任务

依赖方向：本模块只依赖 models / notify_service，**不 import scheduler**
（scheduler 反过来 import 本模块的 run_daily），避免循环 import。
"""

import json
import re
from calendar import isleap
from datetime import date

from sqlalchemy.orm import Session

from ..database import month_day_expr
from ..models import BirthdaySettings, Student
from .notify_service import deliver_now, recipients

# 单行设置表固定的主键
SETTINGS_ID = 1

# 模板认的占位符。和 webhook 模板同一条口径：只认这几个，值全部由服务端生成，
# 用户模板只能引用、不能定义
_PLACEHOLDER = re.compile(r"\{\{\s*(name|age|class)\s*\}\}")
# 只用来「找出所有花括号」做校验，不参与替换
_BRACES = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
ALLOWED_PLACEHOLDERS = ("name", "age", "class")

# 没填模板时用的默认文案。同一份常量也会回给前端当 placeholder ——
# 前端灰字里看到的就是真会发出去的那句
DEFAULT_GREET_TEMPLATE = "{{name}}同志，祝你 {{age}} 岁生日快乐！愿新的一岁平安顺遂，万事胜意。"

MAX_TEMPLATE_LEN = 500
# 勾选账号数量上限。全班几十人，防的是调用方传一个巨型数组
MAX_NOTIFY_NOS = 200


# ---------- 设置读写 ----------

def get_settings(db: Session) -> BirthdaySettings:
    """读全局设置。**纯读，不写库**

    行不存在时返回一个「未入库」的默认对象。不在这里补行有两个原因：
    读接口不该有写副作用；而且入库点只有两处（管理员保存、每日任务写
    last_run_date），各写各的不用抢。启动时 main.py 会 ensure_settings() 补一次，
    正常走不到下面这个兜底分支，留着是给「有人手工删了行」兜底。
    """
    row = db.get(BirthdaySettings, SETTINGS_ID)
    return row if row is not None else BirthdaySettings(id=SETTINGS_ID)


def get_or_create_settings(db: Session) -> BirthdaySettings:
    """要往设置行上写东西时用这个

    只 flush 不 commit：事务边界交给调用方 —— 每日任务要把 last_run_date
    和这次运行绑在一次提交里（也是为了避免在会话关闭后再碰这个对象）。
    """
    row = db.get(BirthdaySettings, SETTINGS_ID)
    if row is None:
        row = BirthdaySettings(id=SETTINGS_ID)
        db.add(row)
        db.flush()
    return row


def ensure_settings(db: Session) -> None:
    """启动时把单行设置补出来（幂等，重复启动无副作用）"""
    if db.get(BirthdaySettings, SETTINGS_ID) is None:
        db.add(BirthdaySettings(id=SETTINGS_ID))
        db.commit()


def put_settings(db: Session, data) -> BirthdaySettings:
    """保存设置（整体覆盖）。字段与占位符校验在接口层做过（见 api/birthday.py）"""
    row = get_or_create_settings(db)
    row.banner_enabled = bool(data.banner_enabled)
    row.banner_show_names = bool(data.banner_show_names)
    row.greet_enabled = bool(data.greet_enabled)
    row.greet_template = (data.greet_template or "").strip()
    row.notify_enabled = bool(data.notify_enabled)
    # 去重保序（dict.fromkeys 保序）：存的就是管理员勾选的顺序
    row.notify_student_nos = dump_notify_nos(list(dict.fromkeys(data.notify_student_nos)))
    db.commit()
    db.refresh(row)
    return row


def parse_notify_nos(raw: str) -> list[str]:
    """读取勾选的学号（JSON 数组 → list）。坏值一律当空，不抛

    库里那串是历史数据，不能因为一次手工改库就让首页条幅接口 500。
    """
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    return [str(x) for x in items if isinstance(x, (str, int)) and str(x)]


def dump_notify_nos(nos: list[str]) -> str:
    return json.dumps(nos, ensure_ascii=False)


# ---------- 今日寿星 ----------

def age_on(birth: date, today: date) -> int:
    """这个人在 today 这天**庆祝**的岁数。

    今天正好是生日时，算出来就是「今天要过的岁数」。

    唯一要单独说的是 2 月 29 日出生的人：非闰年没有 02-29，birthday_month_days()
    会把他们的生日提前到 02-28 过。可按普通日期比较，02-28 还排在 02-29 前面，
    会被当成「今天还没过生日」而少算一岁 —— 条幅上写着「今天生日」，祝福语里
    却写着「25 岁生日快乐」而他要过的是 26 岁，自相矛盾。所以提前庆祝的这一天，
    就按生日当天算。

    注：student_service.get_statistics（student_service.py:325）里那份算法**故意
    不跟着改** —— 那边统计的是「实际年龄」，02-29 出生的人在非闰年的 02-28 确实
    还差一天才满岁。一个算「庆祝几岁」、一个算「实际几岁」，用途不同，
    不要为了「看起来一致」而合并回一份。
    """
    if (
        (birth.month, birth.day) == (2, 29)
        and (today.month, today.day) == (2, 28)
        and not isleap(today.year)
    ):
        # 只有非闰年会走到这里：闰年的 02-28 不是 02-29 出生者的生日，
        # birthday_month_days() 也不会把他选进寿星名单
        return today.year - birth.year
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def birthday_month_days(today: date) -> set[str]:
    """今天该给哪些「月-日」过生日

    平常就是今天这一个。唯一特殊的是 2 月 29 日：非闰年根本没有这一天，
    只比月日的话这批人**四年才会被记起一次**。所以非闰年的 02-28 把 02-29
    一起算上（提前一天过），闰年正常按当天算。

    注意：student_service 里那个「未来 N 天内过生日」的筛选**没有**这个兜底，
    所以非闰年的 02-28，条幅可能比名单筛选多出一个人 —— 这是有意的，
    不动既有筛选的行为。
    """
    key = today.strftime("%m-%d")
    days = {key}
    # 闰年判断用标准库的 isleap（age_on 里还要用一次）：手写「四年一闰、
    # 百年不闰、四百年再闰」是经典易错点，交给标准库更省心
    if key == "02-28" and not isleap(today.year):
        days.add("02-29")
    return days


def today_birthdays(db: Session, today: date | None = None) -> list[dict]:
    """今天过生日的人（纯数据 dict）

    比月日、自动跨年，NULL 出生日期天然被排除；写法与
    student_service.py:118-126 同一条路子，不另造一套按年比对的逻辑。

    返回纯数据而不是 ORM 对象：每日任务要「先查完、关会话、再走网络发送」。
    """
    today = today or date.today()
    rows = (
        db.query(Student.student_no, Student.name, Student.class_name, Student.birth_date)
        .filter(Student.birth_date.isnot(None))
        .filter(month_day_expr(Student.birth_date).in_(birthday_month_days(today)))
        .all()
    )
    people = [
        {
            "student_no": no,
            "name": name,
            "class_name": class_name or "",
            "age": age_on(birth, today),
        }
        for no, name, class_name, birth in rows
    ]
    # 稳定顺序：先年龄后姓名，同一批人每次的条幅与通知正文顺序都一致
    people.sort(key=lambda p: (p["age"], p["name"]))
    return people


# ---------- 模板 ----------

def check_template(text: str) -> str | None:
    """校验祝福语模板，返回错误原因，None = 合法。空串合法（= 用默认文案）

    保存时就查一遍占位符，把配错暴露在**保存那一刻**（同 webhook_service
    .check_template 的理由）：模板是自由文本，写错一个花括号的话，要等某天真有
    寿星了才在后台线程里发现，用户完全看不到反馈。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if len(raw) > MAX_TEMPLATE_LEN:
        return f"祝福语太长了，请控制在 {MAX_TEMPLATE_LEN} 个字符以内"
    unknown = set(_BRACES.findall(raw)) - set(ALLOWED_PLACEHOLDERS)
    if unknown:
        allowed = " ".join("{{%s}}" % p for p in ALLOWED_PLACEHOLDERS)
        names = "、".join("{{%s}}" % u for u in sorted(unknown))
        return f"模板里有不认识的占位符：{names}（可用的只有：{allowed}）"
    return None


def render_greeting(template: str, person: dict) -> str:
    """把模板里的占位符换成寿星的信息

    **re.sub 单遍替换，不做 str.replace 连环替换**：str.replace 会把替换进去的
    文本再扫一遍 —— 姓名是学生可以走修改申请改的，姓名里如果写了 {{age}}，
    第二轮就会被展开成年龄，等于让被祝福的人改写了模板。单遍替换 + 服务端生成的
    ctx，替换值永远越不出模板的边界。（理由同 webhook_service._render）
    """
    raw = (template or "").strip() or DEFAULT_GREET_TEMPLATE
    ctx = {
        "name": person["name"],
        "age": str(person["age"]),
        "class": person["class_name"] or "本班",
    }
    return _PLACEHOLDER.sub(lambda m: ctx[m.group(1)], raw)


# ---------- 文案组装 ----------

def build_summary(people: list[dict]) -> tuple[str, str]:
    """功能 3 的汇总文案：几人生日、几岁、是谁

    **测试接口和每日任务共用这一个函数** ——「发送测试」的全部价值就是
    「测的就是真发的那段文案」；两处各写一份的话，改了真发的文案测试还在验证
    旧格式，等于白测。

    按年龄分组，同岁的人排一行：

        今天有 3 位同志生日
        20 岁：张三、李四
        21 岁：王五

    只列姓名不列学号 —— 收件人是管理员勾选的账号，不需要更多身份信息。
    单人也是一条路径，不写「祝他 / 祝他们」这种会随人数变性的代词，少一条分支。
    """
    groups: dict[int, list[str]] = {}
    for p in people:
        groups.setdefault(p["age"], []).append(p["name"])
    title = f"今天有 {len(people)} 位同志生日"
    body = "\n".join(f"{age} 岁：" + "、".join(names) for age, names in sorted(groups.items()))
    return title, body


# ---------- 每日任务 ----------

def run_daily(db: Session, today: date | None = None) -> bool:
    """每日生日任务：给寿星本人发祝福 + 给勾选的账号发汇总。返回本轮是否执行了

    幂等靠 birthday_settings.last_run_date，只由本函数（即调度线程）写，
    单进程内不存在并发。

    **标记在发送之后才写（至少一次）**：顺序反过来（先写标记再发）的话，进程一旦
    在标记落库后、消息发出前挂掉，这一天就永久静默跳过；反过来最多重发一条 ——
    对生日祝福来说，多收一条远比「没人记得」轻。崩溃窗口是毫秒级。

    今天没人过生日时也会写标记（表示「这轮跑过了」），省得当天反复扫全表。
    """
    today = today or date.today()
    cfg = get_or_create_settings(db)
    if cfg.last_run_date == today:
        return False

    people = today_birthdays(db, today)
    # 组装阶段把要用的设置值全部读出来（下面 close 之后 cfg 就脱离会话了）
    jobs: list[tuple] = []
    if people:
        if cfg.greet_enabled:
            for p in people:
                jobs.append((
                    recipients(db, only_no=p["student_no"]),
                    "祝你生日快乐",
                    render_greeting(cfg.greet_template, p),
                ))
        if cfg.notify_enabled:
            nos = parse_notify_nos(cfg.notify_student_nos)
            if nos:
                title, body = build_summary(people)
                for no in nos:
                    jobs.append((recipients(db, only_no=no), title, body))

    # recipients() 必须在会话还开着时调（它查 users 表的推送配置），上面已查完。
    # 下面要走网络，先把连接还回去 —— SQLite 是单写者，不该让外网请求占着那把锁。
    # Recipients 是纯数据对象，会话关了照样能发（这正是它设计成纯数据的原因）。
    db.close()
    for targets, title, body in jobs:
        deliver_now(targets, title, body, page="/dashboard")

    # ⚠ 上面 close() 之后 cfg 已脱离会话，在它身上赋值再 commit 是**静默不落库**的。
    # 重新 get 一次，拿挂在新事务上的对象
    mark = get_or_create_settings(db)
    mark.last_run_date = today
    db.commit()

    # 每天跑完**一定**打一行，把「跑了」和结果一起说出来 —— 运维在 docker logs 里
    # 就能确认这个功能是活的。所以三种情况都要有输出，尤其是「跑了但没发」：
    # 没有这一行的话，「开关没开」和「线程早就死了」在日志里长得一模一样。
    names = "、".join(p["name"] for p in people)
    if not people:
        result = "今日无人过生日，未发送"
    elif not jobs:
        result = f"今日 {len(people)} 位寿星（{names}），但推送开关未开启，未发送"
    else:
        result = f"今日 {len(people)} 位寿星（{names}），已发 {len(jobs)} 条通知"
    print(f"[生日] {today.isoformat()} 检查完成：{result}", flush=True)
    return True

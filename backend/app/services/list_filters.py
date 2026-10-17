"""列表页共用的筛选条件：关键词与提交日期

各列表接口的查询形状不同，这里只抽两件确实一样的事，免得每个接口各写一遍、
哪天口径变了要满仓库找：

- `keyword_like`：给出的列里**任一列**包含关键词就命中。姓名、学号、标题、备注
  这类短字段用的都是它。空关键词返回 None，调用方据此跳过过滤（不是过滤出一个空集）。
- `created_between`：按 **自然日** 圈一个时间列，含首尾两天。前端日期选择器给的是
  「哪一天」而不是「哪个时刻」，所以右边界取 end 的次日零点。
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import or_


def keyword_like(keyword: str | None, *columns):
    """任一列 LIKE %关键词%；没给关键词（或只有空白）时返回 None"""
    kw = (keyword or "").strip()
    if not kw:
        return None
    pattern = f"%{kw}%"
    return or_(*(column.like(pattern) for column in columns))


def created_between(query, column, start: date | None, end: date | None):
    """按日期圈列，含首尾两天。start / end 可以只给一个"""
    if start:
        query = query.filter(column >= datetime.combine(start, time.min))
    if end:
        query = query.filter(column < datetime.combine(end + timedelta(days=1), time.min))
    return query

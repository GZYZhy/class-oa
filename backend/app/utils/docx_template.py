"""Word 模板的占位符替换

模板正文里写 `{{TOKEN}}`，生成时换成实际值。好处是模板本身不含任何学校 / 班级的
具体信息 —— 换一所学校、换一届班级只要改配置，不用动模板、更不用改代码。

**模板里每个 {{TOKEN}} 必须整个落在一个 run 里**（在 Word 里就是别把「{」和后面的
字母用不同的字体/下划线格式分开）。这样替换时直接改 run 的文字就行，run 上的
下划线、字号、加粗全都原样保留 —— 「（学号：____）」那种填空下划线就是这么留住的。

要是跨了 run，就得先把整段拼起来再回写，那会把这个段落的格式统一掉，填空下划线
会消失。所以这里不做「跨 run 的占位符」这种补救，宁可让模板作者注意一下。
"""

import re

TOKEN_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def fill(doc, values: dict[str, str]) -> None:
    """把文档里所有 {{TOKEN}} 换成 values[TOKEN]

    分三种情况，都是为了「出错时看得见」：
    - **键不在 values 里** —— 原样留着。那是模板和代码对不上（占位符名字写错、
      或者换了模板没跟着改代码），生成出来的文档上直接看得见 {{XXX}}。
    - **键在、值非空** —— 换成值。
    - **键在、值为空**（配置没填）—— 印成空白。这类是运维自己能看到的事，
      不该把 {{ADDRESS}} 印到要盖章的正式表格上。

    段落和表格单元格都会走到：模板的正文和表格里都可能出现占位符。
    """
    def sub(match):
        token = match.group(1)
        if token not in values:
            return match.group(0)
        return values[token] or ""

    for paragraph in _paragraphs(doc):
        for run in paragraph.runs:
            if "{{" in run.text:
                run.text = TOKEN_RE.sub(sub, run.text)


def _paragraphs(doc):
    """文档里所有段落：正文的 + 每张表格每个单元格里的

    只下探一层就够了 —— 这几份模板的表格里没有嵌套表格。
    """
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs

# assets/fonts —— 生成 PDF 用的字体

## SimSun.ttf

请假审批表 PDF（`app/utils/leave_pdf.py`）用它排版。放进仓库是为了**换机器/换服务器渲染结果一致**：
reportlab 用 `TTFont` 加载后会把字体**子集嵌入** PDF（生成出的文件里字体名是 `AAAAAA+SimSun`），
所以拿到 PDF 的机器不装宋体也不会变成方块。

- 来源：macOS 本机 `/Users/gzyzhy/Library/Fonts/SimSun.ttf`
- 大小 10,518,768 字节，md5 `6e86ff9e950d559fdd77c6d3ce8c52ec`
- **必须是纯 TTF**：reportlab 的 `TTFont` 不认 `.ttc`（微软的 `simsun.ttc` 是字体集，加载会报错）

## 授权提醒

宋体（SimSun）是微软 / 中易的**商用字体**，随源码一起分发存在再分发授权风险。
本项目为班级内部自用，页面与镜像都不对外公开发布，风险可控；若要彻底规避，
换一份 SIL OFL 等开源许可的宋体（如思源宋体 Noto Serif CJK / Source Han Serif）即可 ——
改 `leave_pdf.py` 里 `_register_font()` 的文件名与字体名就行，版式数值不用动
（但字宽会略有差别，`test_leave_pdf.py` 的宽度断言要重跑一遍）。

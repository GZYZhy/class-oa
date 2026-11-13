"""附件上传的共用限制：后缀白名单、单件大小、每条/每题最多几个

为什么单独一份：通知公告附件、收集的附件题用的是同一套口径（后端校验、前端
accept、提示文案都要对得上）。散在两处写，改一处忘另一处就会出现「通知能传
pdf、收集传不了」这种事，而且只会被学生撞上才发现。

意见反馈**刻意更窄**（不收压缩包，见 api/feedback.py 里的说明），它自己留一份
白名单，不并进来。

不收 svg/html/js（能被浏览器当页面渲染）、不收带宏的 docm/xlsm/pptm（宏会执行）。
"""

# 允许的附件类型：图片 / 视频 / 音频 / 文档 / 压缩包
ALLOWED_ATTACHMENT_EXTENSIONS = frozenset({
    # 图片（heic/heif 是 iPhone 拍照的默认格式）
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif",
    # 视频
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
    # 音频
    ".mp3", ".m4a", ".wav",
    # 文档（wps/et/dps 是 WPS 的文字/表格/演示）
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".pdf", ".txt", ".md", ".wps", ".et", ".dps",
    # 压缩包
    ".zip", ".rar", ".7z",
})

# 单个附件的大小上限（不是几个合计）
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

# 通知每条最多附件数，收集题未指定数量时也使用这个默认值
MAX_ATTACHMENTS = 3

# 提示文案里那句「支持什么」，前后端各写一遍容易走样，收在这里
ATTACHMENT_ACCEPT_HINT = "图片 / 视频 / 音频 / 文档 / 压缩包"

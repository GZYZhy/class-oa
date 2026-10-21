"""角色等级。数值越大权限越高，等级 >= 要求即放行

放在 utils 而不是 api/deps.py，是因为 services 层也要用（比如投票分享页把
表决范围反推成「班委」）—— 全项目的 services 都不 import api，角色口径只能
有一份，所以挪到这里，deps 和 services 都从这里引。
"""

# 角色等级：数值越大权限越高
ROLE_RANK = {"student": 0, "committee": 1, "admin": 2}

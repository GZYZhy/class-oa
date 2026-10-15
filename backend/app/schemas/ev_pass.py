"""电动车通行证补办 schema"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# 提交接口是 multipart（brand / plate_number / license_file 一起传），
# 参数在 api/ev_passes.py 里用 Form/File 声明，所以这里没有 Create schema


class EvPassRequestResponse(BaseModel):
    """申请记录响应"""
    id: int
    student_id: int
    student_name: Optional[str] = None
    student_no: Optional[str] = None
    brand: Optional[str] = None
    plate_number: Optional[str] = None
    license_original_name: Optional[str] = None
    # pending 待受理 / accepted 已受理 / correcting 待补正 / approved 已通过 / rejected 已驳回
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    # 退回补正的理由（受理后发现材料不对）。和 reject_reason 不是一回事：补正是
    # 「补齐了还能批」，驳回是「这件事不批了」
    correction_reason: Optional[str] = None
    # 经办班委签字：批准时选一位管理员签名，或选「暂不签署」（那时三列全空）
    sign_name: str = ""
    # 派生：签没签字。签字图**副本的文件名**不进响应 —— 前端只需要知道
    # 「已由张三签字」/「暂未签署」，拿不到副本名也就拼不出别的下载地址
    has_sign: bool = False

    class Config:
        from_attributes = True


class EvPassRejectRequest(BaseModel):
    """驳回申请"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")


class EvPassCorrectRequest(BaseModel):
    """退回补正：受理后发现材料不对，打回让申请人补齐（和驳回不是一回事）"""
    reason: str = Field(..., min_length=1, max_length=500, description="要补什么材料")


class EvPassSignature(BaseModel):
    """经办班委用谁的签字（批准时收一次，之后补签字时再收一次）

    只有这一项 —— 「暂不签署」就是空串。**没有意见字段**：这份表上没有意见栏，
    落款处只有一行签字（请假那份才有班导师意见，两边的 body 不一样）。
    """
    sign_no: str = Field("", max_length=20, description="签字人登录名，空串=暂不签署")

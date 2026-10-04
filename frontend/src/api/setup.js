import request from '@/utils/request'

/**
 * 初始化状态：还差不差东西
 *
 * 只读，登录就能问。浮层靠它渲染「已导入 N 名学生」和选人下拉。
 */
export function getSetupState() {
  return request({
    url: '/setup/state',
    method: 'get'
  })
}

/**
 * 指定管理员，完成初始化
 *
 * 后端会在这一个事务里把该学号提为管理员、并删掉临时账号 ——
 * 所以这次响应回来之后，手里这个会话就已经失效了（下一个请求会 401）。
 * 调用方拿到结果就该清登录态、回登录页。
 */
export function finishSetup(adminStudentNo) {
  return request({
    url: '/setup/finish',
    method: 'post',
    data: { admin_student_no: adminStudentNo }
  })
}

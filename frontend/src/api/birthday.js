import request from '@/utils/request'

/** 首页今日生日条幅。匿名只回人数，登录且开关打开时才回姓名 */
export function getBirthdayToday() {
  return request({
    url: '/birthday/today',
    method: 'get'
  })
}

/** 读取生日关怀设置（仅管理员） */
export function getBirthdaySettings() {
  return request({
    url: '/admin/birthday/settings',
    method: 'get'
  })
}

/** 保存生日关怀设置（全量覆盖） */
export function saveBirthdaySettings(data) {
  return request({
    url: '/admin/birthday/settings',
    method: 'put',
    data
  })
}

/** 给当前管理员自己发一条生日汇总测试消息 */
export function testBirthdayNotify() {
  return request({
    url: '/admin/birthday/test',
    method: 'post'
  })
}

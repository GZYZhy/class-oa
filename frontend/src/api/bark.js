import request from '@/utils/request'

/** 读取自己的 Bark 推送设置（设备 key 和图标预览地址） */
export function getBarkSetting() {
  return request({
    url: '/auth/bark',
    method: 'get'
  })
}

/** 保存设备 key；传空串表示解除绑定 */
export function saveBarkSetting(barkKey) {
  return request({
    url: '/auth/bark',
    method: 'put',
    data: { bark_key: barkKey }
  })
}

/** 发一条测试推送，用来当场确认 key 填对了 */
export function testBarkPush() {
  return request({
    url: '/auth/bark/test',
    method: 'post'
  })
}

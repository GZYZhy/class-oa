/**
 * 资料下载：清单与分享外链
 *
 * 清单接口一直是 Downloads.vue 里直接用 request 调的（返回格式从 v1 起没变），
 * 这里只放分享外链相关的两个调用 —— 一个要登录（创建），一个公开（落地页读取）。
 */
import request from '@/utils/request'

/**
 * 给一份资料创建外链
 *
 * @param {number} resourceId 资料 ID
 * @param {number} days 有效期天数：1 / 7 / 30，0 表示永久
 */
export function createResourceShare(resourceId, days) {
  return request({
    url: `/resources/${resourceId}/share`,
    method: 'post',
    data: { days }
  })
}

/**
 * 外链落地页的数据（免登录）
 *
 * token 不存在时后端回 404；过期 / 已吊销时回 200 且 valid=false，
 * reason 说明是 expired 还是 revoked。
 */
export function getResourceShareInfo(token) {
  return request({
    url: `/resources/share/${encodeURIComponent(token)}/info`,
    method: 'get'
  })
}

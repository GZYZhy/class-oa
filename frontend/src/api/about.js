import request from '@/utils/request'

/** 班级概况：人数、性别分布、班委名单（登录即可，普通学生也能看） */
export function getAbout() {
  return request({
    url: '/about',
    method: 'get'
  })
}

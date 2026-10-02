import request from '@/utils/request'

// 我申请的办件
export function getMySubmitted() {
  return request.get('/workspace/submitted').then((res) => res.data)
}

// 我参与处理的办件
export function getMyInvolved() {
  return request.get('/workspace/involved').then((res) => res.data)
}

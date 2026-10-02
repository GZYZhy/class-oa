import request from '@/utils/request'

// 注意：request 的响应拦截器（utils/request.js）已经把 axios 的 response 解包成
// response.data 了，这里**不能再接一次 .then((res) => res.data)**。
// 后端这两个接口返回的是数组，对数组取 .data 得到 undefined，赋给列表 ref 之后
// 模板里的 xxx.length 会抛 "undefined is not an object"，整个 tab 渲染中断 ——
// 表现就是办件空间一片空白、连「暂无申请记录」都显示不出来。

// 我申请的办件
export function getMySubmitted() {
  return request.get('/workspace/submitted')
}

// 我参与处理的办件
export function getMyInvolved() {
  return request.get('/workspace/involved')
}

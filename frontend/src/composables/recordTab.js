import { watch } from 'vue'
import { useRoute } from 'vue-router'

/**
 * 让「我的记录」页签能被链接直接打开。
 *
 * 站内信（「请假申请已通过」这类）和「我的信息 → 办件空间」的详情按钮，
 * 链接统一带 `?tab=record` —— 意思是「落到这个页面的记录页签」，
 * 而不是只把页面打开、让人再点一次页签。也接受本页自己的页签名
 * （history / mine / my），手写链接时不必记那套约定。
 *
 * 用法：页签照常 `const activeTab = ref('apply')`，紧跟一行
 * `syncRecordTab(activeTab, 'history')`。
 *
 * 之所以做成「传 ref 进去同步」而不是直接返回一个 ref：
 * 页签的初值仍留在页面自己的那行代码里，读代码时一眼能看到默认页签是哪个。
 *
 * @param {import('vue').Ref<string>} activeTab 页面自己的页签 ref
 * @param {string} recordTab 本页「我的记录」的页签名
 */
export function syncRecordTab(activeTab, recordTab) {
  const route = useRoute()

  function apply() {
    const tab = route.query.tab
    if (tab === 'record' || tab === recordTab) activeTab.value = recordTab
  }

  // immediate：首次进入时查询串里就有 tab=record，要在渲染前切过去；
  // watch：已经停在本页时再点一条链接，组件不会重新挂载，靠这里补一次切换
  watch(() => route.query.tab, apply, { immediate: true })
}

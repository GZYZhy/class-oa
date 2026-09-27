/**
 * 站点品牌信息
 *
 * 值来自 /site-config.js（怎么注入的、为什么不能用 VITE_* 构建期变量，
 * 见 frontend/site-config.js.template 头部的说明）。
 *
 * 集中在这里，和 utils/roles.js 一个道理：谁要显示班级名都从这里取，别各自写死。
 *
 * 这里**不做兜底**：.env 里没配，取出来就是空字符串。空白一眼能看见，
 * 比悄悄退回某个写死的旧值好排查。
 */

const raw = window.__SITE__ || {}

export const SITE = Object.freeze({
  /** 站点全名，如「示例班信息管理系统」 */
  name: raw.name || '',
  /** 班级简称，如「示例班」 */
  shortName: raw.shortName || '',
  /** 副标题，如「示例大学示例学院示例专业系」 */
  subtitle: raw.subtitle || '',
  /** 所属学院 */
  college: raw.college || '',
  /** 所属专业 */
  major: raw.major || '',
  /** 页脚署名，**含 HTML**（.env 里可以直接写链接、换行），用 v-html 渲染 */
  footer: raw.footer || ''
})

/**
 * 页脚版权行，**是 HTML，必须用 v-html 渲染**（就是下面那个 span 里的事）。
 *
 * 年份取运行时当前年份：写死会跨年过期，做成配置又要每年改一次。
 *
 * 这里的 HTML 来自服务器上的 .env，只有运维能改，不是用户输入 ——
 * 所以 v-html 在这里是安全的。但也正因为如此，别把它接到任何用户能影响的值上。
 */
export const COPYRIGHT_HTML = `© ${new Date().getFullYear()} ${SITE.footer}`

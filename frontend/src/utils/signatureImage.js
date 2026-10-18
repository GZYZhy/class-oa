/**
 * 手写签名的图片处理：从画布里找出墨迹范围，裁掉四周空白，导出透明底 PNG。
 *
 * 为什么一定要裁边：后端生成 PDF 时是把整张图**等比缩放进签字框**的
 * （见 backend/app/utils/pdf_kit.py）。画布四周的空白会一起占尺寸，
 * 不裁的话真正写出来的名字会被缩得很小。
 *
 * 为什么是 PNG：墨迹纯黑、背景透明，插进 PDF 不会出现一块白底。
 */

/** 透明通道超过这个值才算墨迹；再低就会把抗锯齿的浅色边缘也算进去 */
const ALPHA_THRESHOLD = 8

/**
 * 找出不透明像素的包围盒。
 *
 * @param {Uint8ClampedArray|number[]} rgba getImageData().data，逐像素 RGBA
 * @param {number} width 画布宽（设备像素）
 * @param {number} height 画布高（设备像素）
 * @returns {{x:number,y:number,width:number,height:number}|null} 没有墨迹时返回 null
 *
 * 单独抽成纯函数是为了能直接测边界：canvas 本身在 SSR 测试里拿不到。
 */
export function findInkBounds(rgba, width, height, threshold = ALPHA_THRESHOLD) {
  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1

  for (let y = 0; y < height; y += 1) {
    const row = y * width
    for (let x = 0; x < width; x += 1) {
      // 每个像素 4 个字节，第 4 个是 alpha
      if (rgba[(row + x) * 4 + 3] > threshold) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }

  if (maxX < 0) return null
  return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 }
}

/**
 * 把签名画布导出成透明底 PNG。
 *
 * 步骤：找墨迹 → 四周留一点白 → 超过 maxWidth 就等比缩小 → toBlob。
 * 限制宽度是为了体积：手写签名在 PDF 里最大也就几厘米宽，1000 像素绰绰有余，
 * 而一张 1200×1600 的整画布 PNG 会白白多出几百 KB。
 *
 * @returns {Promise<{blob: Blob, width: number, height: number}|null>} 空画布返回 null
 */
export async function exportSignaturePng(canvas, { maxWidth = 1000 } = {}) {
  const ctx = canvas?.getContext?.('2d')
  if (!ctx || !canvas.width || !canvas.height) return null

  const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const bounds = findInkBounds(data, canvas.width, canvas.height)
  if (!bounds) return null

  // 留一圈边，免得圆头笔画被切掉。按墨迹高度取 6%，最少 4 个设备像素
  const pad = Math.max(4, Math.round(bounds.height * 0.06))
  const sourceWidth = bounds.width + pad * 2
  const sourceHeight = bounds.height + pad * 2
  const scale = Math.min(1, maxWidth / sourceWidth)

  const out = document.createElement('canvas')
  out.width = Math.max(1, Math.round(sourceWidth * scale))
  out.height = Math.max(1, Math.round(sourceHeight * scale))

  const outCtx = out.getContext('2d')
  outCtx.imageSmoothingEnabled = true
  outCtx.imageSmoothingQuality = 'high'
  // 只画墨迹那一块，四周的透明留白由目标画布自己的尺寸提供
  outCtx.drawImage(
    canvas,
    bounds.x, bounds.y, bounds.width, bounds.height,
    Math.round(pad * scale), Math.round(pad * scale),
    Math.max(1, Math.round(bounds.width * scale)),
    Math.max(1, Math.round(bounds.height * scale))
  )

  const blob = await new Promise((resolve) => out.toBlob(resolve, 'image/png'))
  return blob ? { blob, width: out.width, height: out.height } : null
}

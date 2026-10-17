/**
 * 上传前压缩图片
 *
 * 手机拍的证明材料、证件照动辄 5-10MB，实际要看清的只是纸面上的字，原图上传
 * 既慢又占磁盘。这里在浏览器里用 canvas 重新编码一次：长边最多 2000px（A4 纸
 * 拍成照片，2000px 也够看清小字），JPEG 质量 0.85。
 *
 * 几个刻意的取舍：
 * - 只处理图片，PDF 原样放行；
 * - GIF 不处理 —— canvas 只会留下第一帧，动图就没了；
 * - 小于阈值的文件不动，本来就不大的图没必要再糊一遍；
 * - 压完反而更大、或解码失败，一律退回原文件：压缩是优化，不能变成上传失败的理由。
 */

// 超过 1MB 才压。手机直出的照片基本都在这个数以上，截图/表情包不会被动
export const COMPRESS_THRESHOLD = 1024 * 1024
// 长边上限。再大对肉眼没有帮助，只会白占流量和磁盘
export const MAX_EDGE = 2000
// JPEG 质量。0.85 放在 2000px 的图上，纸面小字仍然清晰；再低画质下降能看出来
export const QUALITY = 0.85

/** 等比缩到长边不超过 maxEdge；本来就不超就原样返回 */
export function fitSize(width, height, maxEdge = MAX_EDGE) {
  const edge = Math.max(width, height)
  if (!edge || edge <= maxEdge) return { width, height }
  const scale = maxEdge / edge
  return { width: Math.round(width * scale), height: Math.round(height * scale) }
}

/** 这个文件要不要压 */
export function needsCompress(file, threshold = COMPRESS_THRESHOLD) {
  if (!file || !file.type || !file.type.startsWith('image/')) return false
  // 动图转成 JPEG 会只剩第一帧，不如不压
  if (file.type === 'image/gif') return false
  return file.size > threshold
}

/** 压缩后统一存成 JPEG，文件名跟着换后缀（后端按后缀决定存盘文件名） */
export function jpegName(name) {
  return `${(name || 'image').replace(/\.[^.]+$/, '')}.jpg`
}

/** 解码成能画进 canvas 的图；手机照片的 EXIF 方向由 imageOrientation 转正 */
async function loadBitmap(file) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file, { imageOrientation: 'from-image' })
    } catch (e) {
      // 个别浏览器不认这个选项，退回普通解码
      return await createImageBitmap(file)
    }
  }
  // 老 Safari 没有 createImageBitmap，用 <img> 解
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('图片解码失败'))
    }
    img.src = url
  })
}

/**
 * 需要时把图片压小，返回新 File；不需要或失败时原样返回。
 * 参数留给测试和个别场景覆盖，正常调用直接 await compressImage(file)。
 */
export async function compressImage(file, options = {}) {
  const { maxEdge = MAX_EDGE, quality = QUALITY, threshold = COMPRESS_THRESHOLD } = options
  if (!needsCompress(file, threshold)) return file

  try {
    const bitmap = await loadBitmap(file)
    const { width, height } = fitSize(bitmap.width, bitmap.height, maxEdge)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height

    const ctx = canvas.getContext('2d')
    // PNG 的透明区转成 JPEG 会变黑，先铺一层白底
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, width, height)
    ctx.drawImage(bitmap, 0, 0, width, height)
    bitmap.close?.()

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', quality)
    )
    // 压完没变小就不折腾了
    if (!blob || blob.size >= file.size) return file

    return new File([blob], jpegName(file.name), {
      type: 'image/jpeg',
      lastModified: Date.now()
    })
  } catch (e) {
    return file
  }
}

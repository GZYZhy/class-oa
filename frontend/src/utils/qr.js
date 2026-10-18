/**
 * 把一段链接画成带校徽的二维码（data URL）
 *
 * 二维码用最高纠错级别 H：中间那块白色校徽会遮住一部分码点，H 留的冗余足够扫。
 * 校徽加载失败就返回纯二维码，不能因为一张图让整个分享入口没有码。
 *
 * 所有 window / document / Image 都在函数里用，SSR import 这个模块是安全的。
 */

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

function roundedRect(ctx, x, y, width, height, radius) {
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + width, y, x + width, y + height, radius)
  ctx.arcTo(x + width, y + height, x, y + height, radius)
  ctx.arcTo(x, y + height, x, y, radius)
  ctx.arcTo(x, y, x + width, y, radius)
  ctx.closePath()
}

/**
 * @param {string} link 要编码的地址
 * @param {{logoUrl?: string, size?: number}} options 校徽地址、画布边长
 * @returns {Promise<string>} PNG data URL
 */
export async function makeQrDataUrl(link, { logoUrl = '/logo.png', size = 720 } = {}) {
  if (!link) throw new Error('缺少链接')

  const QRCode = (await import('qrcode')).default
  const plain = await QRCode.toDataURL(link, {
    width: size,
    margin: 1,
    errorCorrectionLevel: 'H',
    color: { dark: '#000000', light: '#ffffff' }
  })

  try {
    const [qrImage, logo] = await Promise.all([
      loadImage(plain),
      loadImage(logoUrl).catch(() => null)
    ])
    if (!logo) return plain

    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d')
    ctx.drawImage(qrImage, 0, 0, size, size)

    // 白色圆角底 + 校徽：约占二维码 23%，在 H 级纠错的可恢复范围内
    const box = Math.round(size * 0.233)
    const left = Math.round((size - box) / 2)
    ctx.fillStyle = '#ffffff'
    roundedRect(ctx, left, left, box, box, Math.round(box * 0.14))
    ctx.fill()
    const pad = Math.round(box * 0.07)
    ctx.drawImage(logo, left + pad, left + pad, box - pad * 2, box - pad * 2)

    return canvas.toDataURL('image/png')
  } catch (e) {
    // 校徽加载 / 绘制失败：保留纯二维码
    return plain
  }
}

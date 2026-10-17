/**
 * 通行密钥（WebAuthn）的浏览器侧封装
 *
 * 浏览器 API 收的是 ArrayBuffer，后端传的是 base64url 字符串，两边各转一次。
 * 不引 @simplewebauthn/browser：它做的也就是这一层转换，几十行的事，
 * 多一个依赖反而要跟着它的版本走。
 */

/** 当前环境能不能用通行密钥：必须 HTTPS（localhost 除外）且浏览器支持 */
export function isPasskeySupported() {
  return (
    typeof window !== 'undefined' &&
    !!window.PublicKeyCredential &&
    window.isSecureContext
  )
}

/**
 * 能不能用条件式 UI（账号框的自动填充）
 *
 * 支持时页面加载后可以挂起一次 get({mediation:'conditional'})：
 * 用户聚焦账号框，浏览器就把本机的钥匙列进自动填充，选中后才弹生物识别。
 * Safari 16+ / Chrome 108+ 支持；老浏览器返回 false，照常走按钮。
 */
export async function isConditionalPasskeyAvailable() {
  if (!isPasskeySupported()) return false
  if (typeof window.PublicKeyCredential.isConditionalMediationAvailable !== 'function') {
    return false
  }
  try {
    return await window.PublicKeyCredential.isConditionalMediationAvailable()
  } catch (e) {
    return false
  }
}

function b64urlToBytes(value) {
  const pad = '='.repeat((4 - (value.length % 4)) % 4)
  const bin = atob(value.replace(/-/g, '+').replace(/_/g, '/') + pad)
  return Uint8Array.from(bin, (c) => c.charCodeAt(0))
}

function bytesToB64url(buffer) {
  const bytes = new Uint8Array(buffer)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function asBuffer(value) {
  // Safari 偶尔给的是 ArrayBuffer，Chrome 给 TypedArray，统一成 ArrayBuffer
  return value instanceof ArrayBuffer ? value : value.buffer
}

/**
 * 把浏览器的凭据对象转成能 JSON 传的形状
 *
 * 用 toJSON() 不是必须的（Safari 16 没有它），所以这里手动拼。
 * transports 只有登记时才有：告诉服务器这把钥匙是内置的还是 USB 的，仅作展示。
 */
function credentialToJSON(cred) {
  const r = cred.response
  const base = {
    id: cred.id,
    rawId: bytesToB64url(cred.rawId),
    type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults
      ? cred.getClientExtensionResults()
      : {}
  }
  if ('attestationObject' in r) {
    return {
      ...base,
      response: {
        clientDataJSON: bytesToB64url(r.clientDataJSON),
        attestationObject: bytesToB64url(r.attestationObject),
        transports: r.getTransports ? r.getTransports() : []
      }
    }
  }
  return {
    ...base,
    response: {
      clientDataJSON: bytesToB64url(r.clientDataJSON),
      authenticatorData: bytesToB64url(r.authenticatorData),
      signature: bytesToB64url(r.signature),
      userHandle: r.userHandle ? bytesToB64url(r.userHandle) : null
    }
  }
}

/** 登记一把新钥匙：后端先给选项（已含挑战），这里转好类型再弹系统验证框 */
export async function createPasskey(options) {
  const publicKey = {
    ...options,
    challenge: b64urlToBytes(options.challenge),
    user: { ...options.user, id: b64urlToBytes(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c) => ({
      ...c,
      id: b64urlToBytes(c.id)
    }))
  }
  const cred = await navigator.credentials.create({ publicKey })
  return credentialToJSON(cred)
}

/**
 * 用已有钥匙登录：allowCredentials 为空，由浏览器列出本机属于本站的钥匙。
 *
 * - mediation: 'conditional' —— 不弹窗，只把钥匙放进账号框的自动填充；
 * - signal —— 用于中止挂起的自动填充（用户改用按钮时必须先停掉它，
 *   两条流程同时跑会互相覆盖服务端会话里的挑战）。
 */
export async function getPasskey(options, { mediation, signal } = {}) {
  const publicKey = {
    ...options,
    challenge: b64urlToBytes(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c) => ({
      ...c,
      id: b64urlToBytes(c.id)
    }))
  }
  const request = { publicKey }
  if (mediation) request.mediation = mediation
  if (signal) request.signal = signal
  const cred = await navigator.credentials.get(request)
  return credentialToJSON(cred)
}

// 供 Node 侧的单元测试直接测两个编解码函数（SSR 环境里没有 window.PublicKeyCredential）
export const _internal = { b64urlToBytes, bytesToB64url, asBuffer }

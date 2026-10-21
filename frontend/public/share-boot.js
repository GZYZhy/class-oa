;(function () {
  var match = /^\/share\/([a-zA-Z0-9_-]+)\/([^/]+)\/?$/.exec(window.location.pathname)
  if (!match) return

  var hash = window.location.hash
  if (hash && hash !== '#' && hash !== '#/') return

  var target = '#/share/' + match[1] + '/' + match[2]
  try {
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search + target
    )
  } catch (e) {
    window.location.hash = target
  }

  function cleanHash() {
    try {
      if (window.location.hash === target) {
        window.history.replaceState(
          window.history.state,
          '',
          window.location.pathname + window.location.search
        )
      }
    } catch (e) {}
  }

  if (document.readyState === 'complete') {
    setTimeout(cleanHash, 0)
  } else {
    window.addEventListener('load', function () {
      setTimeout(cleanHash, 0)
    })
  }
})()

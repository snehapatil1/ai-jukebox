// Native Gradio handles selection, filtering, playback and downloads.
(function () {
  "use strict";
  if (window.__ajThemeInstalled) return;
  window.__ajThemeInstalled = true;
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    if (document.body) document.body.classList.toggle("dark", theme === "dark");
    var button = document.getElementById("themeToggle");
    if (button) {
      button.textContent = theme === "dark" ? "☀ Light" : "☾ Dark";
      button.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
      button.title = button.getAttribute("aria-label");
    }
  }
  var stored = null;
  try { stored = localStorage.getItem("aj-theme"); } catch (_) {}
  applyTheme(stored === "light" ? "light" : "dark");
  document.addEventListener("click", function (event) {
    if (!event.target.closest("#themeToggle")) return;
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem("aj-theme", next); } catch (_) {}
    applyTheme(next);
  });
  var observer = new MutationObserver(function () {
    var button = document.getElementById("themeToggle");
    if (button && !button.dataset.themeReady) {
      button.dataset.themeReady = "true";
      applyTheme(document.documentElement.getAttribute("data-theme") || "dark");
    }
  });
  observer.observe(document.documentElement, {childList: true, subtree: true});
})();

// Native Gradio is the only playback UI. Fit its full waveform to the panel.
(function () {
  if (window.__ajPlaybackInstalled) return;
  window.__ajPlaybackInstalled = true;
  var tracked = new Set();
  var active = null;
  var userStarted = false;  // playback session begun by the user (Play all / Play / Next track)
  var activeSrc = null;     // last src the active element was asked to play
  function inspect(root, media) {
    root.querySelectorAll("audio[src]").forEach(function (audio) { media.push(audio); });
    root.querySelectorAll("*").forEach(function (node) {
      if (!node.shadowRoot) return;
      fitWaveform(node);
      inspect(node.shadowRoot, media);
    });
  }
  function fitWaveform(host) {
    var root = host.shadowRoot;
    var wrapper = root.querySelector('.wrapper');
    if (!wrapper || !root.querySelector('.canvases')) return;
    var width = host.getBoundingClientRect().width;
    var sourceWidth = wrapper.style.width.endsWith('px') ? parseFloat(wrapper.style.width) : width;
    if (!width || !sourceWidth) return;
    host.style.setProperty('--aj-wave-source-width', sourceWidth + 'px');
    host.style.setProperty('--aj-wave-scale', String(width / sourceWidth));
    if (!root.querySelector('style[data-aj-fit]')) {
      var style = document.createElement('style');
      style.dataset.ajFit = 'true';
      style.textContent = ':host{display:block;width:100%;min-width:0}' +
        '.scroll{overflow-x:hidden!important;width:100%!important}' +
        '.wrapper{width:100%!important;min-width:0!important;overflow:hidden!important}' +
        '.canvases,.progress>div{width:var(--aj-wave-source-width)!important;transform:scaleX(var(--aj-wave-scale));transform-origin:left top}';
      root.appendChild(style);
    }
  }
  function update() {
    var panel = document.getElementById('nowAudio');
    var media = [];
    if (panel) inspect(panel, media);
    var next = media[media.length - 1] || null;
    if (active && active !== next && !active.paused) active.pause();
    active = next;
    if (next) {
      var src = next.currentSrc || next.src;
      if (src !== activeSrc) {
        activeSrc = src;
        // Gradio only swaps the src when the queue advances; it never calls
        // play() (its autoplay option is fixed at component mount). Once the
        // user has started a playback session, play each new item ourselves
        // right after its source changes. A rejected play() promise (e.g.
        // still blocked by autoplay policy) is ignored — the user can press
        // play as usual.
        if (userStarted && next.paused && !next.ended) {
          next.play().catch(function () {});
        }
      }
    }
    media.forEach(function (audio) {
      if (tracked.has(audio)) return;
      tracked.add(audio);
      audio.addEventListener('play', function () {
        userStarted = true;
        tracked.forEach(function (other) { if (other !== audio && !other.paused) other.pause(); });
      });
    });
    tracked.forEach(function (audio) { if (!audio.isConnected && audio !== active) tracked.delete(audio); });
  }
  document.addEventListener('click', function (event) {
    if (event.target.closest('#skipBtn')) userStarted = true;
    if (event.target.closest('#skipBtn, #libraryGallery .thumbnail-item')) {
      if (active && !active.paused) active.pause();
    }
  }, true);
  setInterval(update, 200);
})();

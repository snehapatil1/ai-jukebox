"""Coordinated Gradio surfaces: slate/lavender at night, warm stone by day."""

CUSTOM_CSS = """
:root, [data-theme="dark"] {
  --aj-page: #0f1123; --aj-panel: rgba(30, 34, 62, 0.85); --aj-input: #2a2d4a;
  --aj-hover: #3b3f6e; --aj-text: #f0efff; --aj-muted: #a8b0cc;
  --aj-line: rgba(139, 92, 246, 0.3); --aj-accent: #8b5cf6; --aj-accent-bright: #a78bfa;
  --aj-coral: #f97316; --aj-blue: #06b6d4; --aj-pink: #ec4899;
  --glass-blur: 12px;
  color-scheme: dark;
}
[data-theme="light"] {
  --aj-page: #faf8ff; --aj-panel: rgba(255, 255, 255, 0.92); --aj-input: #ede9fe;
  --aj-hover: #ddd6fe; --aj-text: #1e1b4b; --aj-muted: #6b7280;
  --aj-line: rgba(139, 92, 246, 0.25); --aj-accent: #7c3aed; --aj-accent-bright: #a78bfa;
  --aj-coral: #ea580c; --aj-blue: #0891b2; --aj-pink: #db2777;
  --glass-blur: 8px;
  color-scheme: light;
}
/* Override the component tokens, not just the page behind them. */
html body .gradio-container, html body .gradio-container.dark {
  --body-background-fill: var(--aj-page);
  --body-text-color: var(--aj-text); --body-text-color-subdued: var(--aj-muted);
  --background-fill-primary: var(--aj-panel); --background-fill-secondary: var(--aj-input);
  --block-background-fill: var(--aj-panel); --block-border-color: var(--aj-line);
  --block-label-background-fill: var(--aj-panel); --block-label-text-color: var(--aj-muted);
  --block-title-text-color: var(--aj-text); --block-info-text-color: var(--aj-muted);
  --input-background-fill: var(--aj-input); --input-border-color: var(--aj-line);
  --input-placeholder-color: var(--aj-muted); --input-text-color: var(--aj-text);
  --button-secondary-background-fill: var(--aj-input);
  --button-secondary-background-fill-hover: var(--aj-hover);
  --button-secondary-text-color: var(--aj-text); --button-secondary-border-color: var(--aj-line);
  --border-color-primary: var(--aj-line); --border-color-accent: var(--aj-accent);
  --neutral-50: var(--aj-panel); --neutral-100: var(--aj-input);
  --neutral-200: var(--aj-line); --neutral-800: var(--aj-text);
  --neutral-900: var(--aj-text); --neutral-950: var(--aj-text);
  background: var(--aj-page) !important; color: var(--aj-text) !important;
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px;
  --button-primary-background-fill: #7152a6;
  --button-primary-background-fill-hover: #63468f;
  --button-primary-text-color: #ffffff;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 14px; line-height: 1.5;
  width: 100% !important; min-width: 0; flex: 1 1 100%;
  max-width: 1440px !important; margin-inline: auto;
}
/* Keep waveform measurements from resizing the entire shrink-to-fit app. */
.gradio-container > .main, .gradio-container > .main > .wrap,
.gradio-container main {
  width: 100% !important; min-width: 0 !important; box-sizing: border-box;
}
.gradio-container > .main { max-width: 100% !important; }
html, body, main { background: var(--aj-page) !important; color: var(--aj-text) !important; margin: 0 !important; padding: 0 !important; }
main { min-height: 0 !important; padding: 0 !important; max-height: none !important; }
.gradio-container .block:not(.hide-container), .gradio-container .tabitem,
.gradio-container .form, .gradio-container .group {
  background: var(--aj-panel) !important; border-color: var(--aj-line) !important;
  border-radius: 6px !important;
}
.gradio-container .tabitem { padding: 20px !important; }
.gradio-container .form, .gradio-container .group {
  border-radius: 0 !important; box-shadow: none !important;
}
.gradio-container .block { box-shadow: 0 2px 12px rgba(0,0,0,0.15) !important; }
.gradio-container input:not([type="range"]):not([type="checkbox"]),
.gradio-container textarea, .gradio-container select,
.gradio-container .dropdown-wrap {
  background: var(--aj-input) !important; color: var(--aj-text) !important;
  border-color: var(--aj-line) !important; border-radius: 5px !important;
}
.gradio-container input::placeholder, .gradio-container textarea::placeholder {
  color: var(--aj-muted) !important; opacity: 1;
}
.gradio-container label, .gradio-container .block label span,
.gradio-container .prose, .gradio-container .prose p,
.gradio-container .prose h2, .gradio-container .prose h3 {
  color: var(--aj-text) !important; text-transform: none !important;
}
.gradio-container .info, .gradio-container .prose p, #mainDesc { color: var(--aj-muted) !important; }
/* Generate-tab lyrics code block: Gradio's dark-skin code styling maps to
   neutral tokens that this theme remaps to --aj-text, so in dark mode the
   <pre> background and text both became light lavender (#f0efff) — unreadable.
   Force the app's input/text tokens in dark mode only; light mode keeps
   Gradio's default code styling exactly as before. */
[data-theme="dark"] .gradio-container .prose pre,
[data-theme="dark"] .gradio-container .prose pre code {
  background: var(--aj-input) !important;
  color: var(--aj-text) !important;
}
#mainTitle { color: var(--aj-text); letter-spacing: -0.035em; font-weight: 650; line-height: 1.2; }
.gradio-container .tab-nav { border-color: var(--aj-line) !important; gap: 16px; padding-bottom: 0; }
.gradio-container .tab-nav button {
  color: var(--aj-muted) !important; background: transparent !important;
  border: 0 !important; border-bottom: 2px solid transparent !important;
  border-radius: 0 !important; padding: 12px 4px !important; min-height: 44px;
  font-size: 14px; font-weight: 600;
}
.gradio-container .tab-nav button.selected {
  color: var(--aj-text) !important; border-bottom-color: var(--aj-accent) !important;
}
.gradio-container .tab-nav button:hover { color: var(--aj-text) !important; }

/* === THEME TOGGLE — ACTION BUTTON (switch to the other mode) === */
.theme-toggle, #themeToggle {
  display: inline-flex !important; align-items: center; justify-content: center;
  padding: 8px 18px !important; border-radius: 999px !important;
  font-size: 14px !important; font-weight: 600 !important;
  min-width: 160px !important; min-height: 44px !important;
  cursor: pointer !important; transition: all 0.2s ease !important;
  text-decoration: none !important;
  border: 2px solid transparent !important; outline: none !important;
  letter-spacing: 0.02em;
}
[data-theme="dark"] .theme-toggle, [data-theme="dark"] #themeToggle {
  background: linear-gradient(135deg, #8b5cf6, #06b6d4) !important;
  color: #ffffff !important;
  border-color: rgba(139, 92, 246, 0.5) !important;
  box-shadow: 0 2px 16px rgba(139, 92, 246, 0.4) !important;
}
[data-theme="dark"] .theme-toggle:hover, [data-theme="dark"] #themeToggle:hover {
  background: linear-gradient(135deg, #a78bfa, #22d3ee) !important;
  box-shadow: 0 4px 24px rgba(139, 92, 246, 0.5) !important;
  transform: translateY(-1px);
}
[data-theme="light"] .theme-toggle, [data-theme="light"] #themeToggle {
  background: linear-gradient(135deg, #7c3aed, #0891b2) !important;
  color: #ffffff !important;
  border-color: rgba(124, 58, 237, 0.3) !important;
  box-shadow: 0 2px 12px rgba(124, 58, 237, 0.25) !important;
}
[data-theme="light"] .theme-toggle:hover, [data-theme="light"] #themeToggle:hover {
  background: linear-gradient(135deg, #8b5cf6, #06b6d4) !important;
  box-shadow: 0 4px 20px rgba(124, 58, 237, 0.35) !important;
  transform: translateY(-1px);
}
/* Keyboard focus ring — same accent outline pattern as the rest of the app. */
.theme-toggle:focus-visible, #themeToggle:focus-visible {
  outline: 2px solid var(--aj-accent) !important; outline-offset: 3px !important;
}
.gradio-container button.secondary {
  background: var(--aj-input) !important; color: var(--aj-text) !important;
  border: 1px solid var(--aj-line) !important; border-radius: 6px !important;
}
.gradio-container button.primary {
  background: linear-gradient(135deg, #7c3aed, #6d28d9) !important;
  color: #ffffff !important; border: 1px solid #8b5cf6 !important;
  border-radius: var(--radius-md) !important;
  box-shadow: 0 2px 12px rgba(124, 58, 237, 0.3) !important;
  font-weight: 600; min-height: 44px;
}
.gradio-container button.primary:hover {
  background: linear-gradient(135deg, #8b5cf6, #7c3aed) !important;
  box-shadow: 0 4px 20px rgba(124, 58, 237, 0.4) !important;
  transform: translateY(-1px);
}
.gradio-container button.secondary { min-height: 40px; font-weight: 500; box-shadow: none !important; }
.gradio-container button.secondary:hover {
  background: var(--aj-hover) !important; transform: translateY(-1px);
}
.gradio-container button:disabled { opacity: .55; }
.gradio-container :focus-visible { outline: 2px solid var(--aj-accent) !important; outline-offset: 3px; }
.gradio-container [role="listbox"], .gradio-container .options {
  background: var(--aj-panel) !important; color: var(--aj-text) !important;
  border: 1px solid var(--aj-line) !important; border-radius: var(--radius-sm) !important;
  backdrop-filter: blur(var(--glass-blur)) !important;
}
.gradio-container [role="option"] { color: var(--aj-text) !important; }
.gradio-container [role="option"]:hover { background: var(--aj-hover) !important; }
.gradio-container input[type="checkbox"], .gradio-container input[type="range"] { accent-color: var(--aj-accent); }
.aj-queue-item {
  background: var(--aj-panel); border: 0 !important;
  border-bottom: 1px solid var(--aj-line) !important; border-radius: 0 !important;
  padding: 12px 0 !important; box-shadow: none !important;
}
.aj-queue-item b { color: var(--aj-text) !important; }
.aj-queue-item span, .aj-queue-empty { color: var(--aj-muted) !important; }
/* === GENERATION STATUS BOX === */
.aj-status {
  display: flex; flex-direction: column; gap: 5px;
  padding: 10px 12px; border-radius: 8px;
  background: var(--aj-input); border: 1px solid var(--aj-line);
}
.aj-progress {
  height: 4px; border-radius: 999px; overflow: hidden;
  background: rgba(139, 92, 246, 0.18);
}
.aj-progress-bar {
  width: 35%; height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, var(--aj-accent), var(--aj-blue));
  animation: aj-indeterminate 1.1s ease-in-out infinite;
}
@keyframes aj-indeterminate {
  0% { transform: translateX(-110%); }
  100% { transform: translateX(320%); }
}
.aj-status-main {
  display: flex; align-items: baseline; gap: 6px; min-width: 0;
  color: var(--aj-text); font-size: 13px; font-weight: 600;
  line-height: 1.4;
}
.aj-status-text {
  flex: 0 1 auto; min-width: 0; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.aj-status-time {
  flex: 0 0 auto; color: var(--aj-muted); font-size: 12px; font-weight: 500;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.aj-status-hint { color: var(--aj-muted) !important; font-size: 11px; }
/* Workspace structure: one surface per pane, typography within it. */
.gradio-container .aj-header {
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  padding: 8px 0 24px; margin-bottom: 24px;
  border-bottom: 1px solid var(--aj-line);
}
.gradio-container .aj-eyebrow {
  color: var(--aj-muted) !important; font-size: 11px; font-weight: 600;
  letter-spacing: .12em; text-transform: uppercase !important; margin: 0 0 8px;
}
#mainDesc { max-width: 70ch; line-height: 1.6; margin-top: 8px; }
#studioPanel, #playerPanel {
  min-width: 0 !important; gap: 20px;
  background: var(--aj-panel) !important;
  border: 1px solid var(--aj-line) !important; border-radius: var(--radius-lg) !important;
  padding: 24px !important; box-shadow: 0 4px 24px rgba(0,0,0,0.15) !important;
  backdrop-filter: blur(var(--glass-blur)); -webkit-backdrop-filter: blur(var(--glass-blur));
}
#studioPanel .tabitem { padding: 20px 0 0 !important; border: 0 !important; }
#studioPanel .form, #playerPanel .form,
#studioPanel .group, #playerPanel .group { border: 0 !important; }
.gradio-container .prose h2, .gradio-container .prose h3,
.gradio-container .aj-section-heading {
  color: var(--aj-text) !important; letter-spacing: -.015em;
  font-size: 17px; font-weight: 600; line-height: 1.35;
  margin: 0 0 12px;
}
.gradio-container .prose h3 { font-size: 15px; margin-bottom: 8px; }
.gradio-container .prose p { line-height: 1.6; }
#libraryGallery {
  background: var(--aj-panel) !important; border: 0 !important;
  border-radius: 0 !important; padding: 0 !important;
}
#libraryGallery .grid-wrap { padding: 0 !important; }
#libraryGallery .thumbnail-item {
  background: var(--aj-panel) !important; border: 1px solid var(--aj-line) !important;
  border-radius: var(--radius-md) !important; box-shadow: none !important;
  backdrop-filter: blur(var(--glass-blur)); -webkit-backdrop-filter: blur(var(--glass-blur));
}
#libraryGallery .thumbnail-item:hover { border-color: var(--aj-accent) !important; box-shadow: 0 0 0 1px var(--aj-accent) !important; }
#libraryGallery .thumbnail-item.selected {
  border-color: var(--aj-accent) !important; box-shadow: 0 0 0 2px var(--aj-accent), 0 4px 16px rgba(139, 92, 246, 0.3) !important;
}
#libraryGallery .caption {
  background: var(--aj-panel) !important; color: var(--aj-text) !important;
  font-size: 13px; line-height: 1.4; padding: 8px 10px !important;
  text-shadow: none !important; backdrop-filter: blur(var(--glass-blur));
}
footer { display: none !important; }
@media(max-width: 640px) {
  main { padding: 12px !important; }
  .gradio-container .aj-header { gap: 16px; flex-wrap: wrap; padding-bottom: 20px; margin-bottom: 20px; }
  #studioPanel, #playerPanel { padding: 16px !important; gap: 16px; }
  .gradio-container .tab-nav { gap: 12px; }
  .gradio-container button.secondary { min-height: 44px; }
}
"""

from pathlib import Path

CUSTOM_CSS += Path(__file__).with_name("workspace.css").read_text(encoding="utf-8")

THEME_JS = """
() => {
  const root = document.documentElement;
  function apply(theme) {
    root.dataset.theme = theme;
    // Gradio also uses .dark for its native component styles.
    root.classList.toggle('dark', theme === 'dark');
    document.body.classList.toggle('dark', theme === 'dark');
    document.querySelectorAll('.gradio-container').forEach(el => el.classList.toggle('dark', theme === 'dark'));
    const btn = document.getElementById('themeToggle');
    if (btn) {
      // Action wording: the button always says what it DOES (switch modes),
      // never the name of the current mode — unambiguous in both themes.
      const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
      if (btn.textContent !== label) btn.textContent = label;
      btn.title = label;
      btn.setAttribute('aria-label', label);
      btn.setAttribute('aria-pressed', String(theme === 'light'));
    }
  }
  let saved = 'dark';
  try { if (localStorage.getItem('aj-theme') === 'light') saved = 'light'; } catch (_) {}
  apply(saved);
  if (window.__ajThemeClick) document.removeEventListener('click', window.__ajThemeClick);
  window.__ajThemeClick = event => {
    if (!event.target.closest('#themeToggle')) return;
    event.preventDefault();
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    apply(next);
    try { localStorage.setItem('aj-theme', next); } catch (_) {}
  };
  document.addEventListener('click', window.__ajThemeClick);
  if (window.__ajThemeObserver) window.__ajThemeObserver.disconnect();
  window.__ajThemeObserver = new MutationObserver(() => apply(root.dataset.theme || 'dark'));
  window.__ajThemeObserver.observe(document.body, {childList:true, subtree:true});
}
"""

# Native YouTube mode ("Sifat" tugmasi) — built, then shelved
![alt text](<Screenshot 2026-07-15 at 16.43.55.png>)
**Status: not in the codebase.** Built and verified working on 2026-07-15, then removed
the same day at the owner's request: the "Oddiy pleyer" exit pill sat top-right *inside*
the player and covered YouTube's own top-right controls (including the gear/quality
area the feature existed to expose). Decision: not needed for now; keep the design +
code here so it can be restored quickly.

## Why it existed

Users can't change video quality: the IFrame API's `setPlaybackQuality` /
`suggestedQuality` have been official no-ops since 2019, so the only real quality
selector is the gear in YouTube's **native** controls — which our custom chrome
disables (`controls:0` + `pointer-events:none`, see `docs/architecture.md` → Custom
Video Player). The feature was a toggle that rebuilt the player with native controls
on demand (position + play state preserved), and an exit pill to rebuild back.

Verified working end-to-end: rebuild both directions, position/play state preserved,
`record_view` fired only once across rebuilds (tracker's module-scope `recorded` /
`completed` flags survive), gear → manual quality selection worked.

## The problem to solve before re-enabling

The exit pill (`position:absolute; top:10px; right:10px` inside `#vp`) overlaps
YouTube's top-right hover chrome. Better placements to try:
- a strip **below** the video wrapper (outside `#vp`), e.g. "YouTube boshqaruvi yoqilgan — Oddiy pleyerga qaytish";
- or bottom-left inside the player, above the native bar.

## Code (as removed — restore from here)

### `templates/learning/lesson_detail.html`

Inside `.vp-controls`, between the rate and fullscreen buttons:

```html
<button type="button" class="vp-btn" id="vp-native" aria-label="Sifat (YouTube boshqaruvi)" title="Sifat (YouTube boshqaruvi)">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/></svg>
</button>
```

Inside `#vp`, after the spinner (the placement that caused the shelving — rework per above):

```html
<button type="button" class="vp-native-exit" id="vp-native-exit">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
  Oddiy pleyer
</button>
```

### `static/js/lesson_player.js`

Element lookups next to the other `getElementById` lines:

```js
var nativeBtn  = document.getElementById('vp-native');
var nativeExit = document.getElementById('vp-native-exit');
```

Block (sat between the playback-rate and fullscreen sections):

```js
// ── Native YouTube mode (quality menu lives in YT's own chrome) ──
// The IFrame API can't set quality (setPlaybackQuality is a no-op), so the
// only real quality selector is YouTube's native gear. This rebuilds the
// player with native controls; toggling back restores our chrome.
function setNative(native) {
  if (!window.__vpRebuild || !player) return;
  hidePoster();
  if (endOv) endOv.hidden = true;
  shell.classList.remove('vp-idle');
  shell.classList.toggle('vp-native', native);
  ready = false;
  pendingPlay = false;
  stopTicker();
  setSpinner(true);  // hidden by CSS while in native mode
  window.__vpRebuild(native);
}
if (nativeBtn)  nativeBtn.addEventListener('click', function () { setNative(true); });
if (nativeExit) nativeExit.addEventListener('click', function () { setNative(false); });
```

### `static/js/lesson_tracker.js`

Replace the direct `new YT.Player(...)` in `onYouTubeIframeAPIReady` with a
`buildPlayer(native, startAt, resume)` helper plus the rebuild hook. The helper is the
existing constructor with two changes — parameterized playerVars and an `onReady`
seek/resume step:

```js
function buildPlayer(native, startAt, resume) {
  player = new YT.Player('yt-player', {
    videoId: VIDEO_ID,
    playerVars: {
      rel: 0, playsinline: 1, iv_load_policy: 3,
      controls: native ? 1 : 0, disablekb: native ? 0 : 1, fs: native ? 1 : 0,
    },
    events: {
      onReady: function () {
        if (startAt > 0 || resume) {
          player.seekTo(startAt, true);      // seekTo on a cued video starts playback…
          if (!resume) player.pauseVideo();  // …so pause right back if it was paused
        }
      },
      onStateChange: function (e) { /* unchanged: recordView/startPoll on PLAYING, markComplete on ENDED */ },
    },
  });
  if (window.__bmSetPlayer) window.__bmSetPlayer(player);
  if (window.__vpSetPlayer) window.__vpSetPlayer(player);
}

window.onYouTubeIframeAPIReady = function () { buildPlayer(false, 0, false); };

// Rebuild the player with/without native YouTube controls, preserving
// position + play state. Called by lesson_player.js ("YouTube rejimi").
window.__vpRebuild = function (native) {
  if (!player) return;
  var t = 0, resume = false;
  try {
    t = player.getCurrentTime() || 0;
    var s = player.getPlayerState();
    resume = (s === YT.PlayerState.PLAYING || s === YT.PlayerState.BUFFERING);
  } catch (e) {}
  try { player.destroy(); } catch (e) {}
  if (!document.getElementById('yt-player')) {   // destroy() removes the iframe without restoring the mount div
    var shell = document.getElementById('vp');
    if (!shell) return;
    var mount = document.createElement('div');
    mount.id = 'yt-player';
    shell.insertBefore(mount, shell.firstChild);
  }
  buildPlayer(native, t, resume);
};
```

### `static/css/style.css`

After the `.vp-loading` rule:

```css
/* Native YouTube mode: the quality menu only exists in YT's own chrome
   (the API can't set quality), so our layers step aside entirely. */
.vp.vp-native iframe { pointer-events: auto; }
.vp.vp-native .vp-gesture,
.vp.vp-native .vp-bar,
.vp.vp-native .vp-spinner { display: none; }
.vp-native-exit {
  position: absolute; top: 10px; right: 10px; z-index: 7;   /* ← the placement to rework */
  display: none; align-items: center; gap: 6px;
  padding: 6px 12px; border: 0; border-radius: 999px;
  background: rgba(8, 15, 13, .82); color: #fff;
  font-size: .8rem; font-weight: 600;
  transition: background .12s;
}
.vp.vp-native .vp-native-exit { display: inline-flex; }
.vp-native-exit:hover { background: rgba(8, 15, 13, .95); }
.vp-native-exit svg { width: 14px; height: 14px; }
```

## Design decisions that still hold if restored

- Mode is **not persisted** — every lesson load starts in custom chrome; native mode is
  an opt-in escape hatch (the title/pause-panel chrome returns while in it).
- Entering native mode calls `hidePoster()` and hides the end overlay; keyboard
  shortcuts keep working (they drive the API, not the DOM).
- Tracker flags (`recorded`, `completed`) are module-scope, so rebuilds never
  double-fire `record_view` / `mark_lesson_complete`.

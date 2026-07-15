(function () {
  'use strict';

  var shell = document.getElementById('vp');
  if (!shell) return;

  var gesture = document.getElementById('vp-gesture');
  var bar     = document.getElementById('vp-bar');
  var seekEl  = document.getElementById('vp-seek');
  var timeEl  = document.getElementById('vp-time');
  var playBtn = document.getElementById('vp-play');
  var icPlay  = document.getElementById('vp-ic-play');
  var icPause = document.getElementById('vp-ic-pause');
  var muteBtn = document.getElementById('vp-mute');
  var icVol   = document.getElementById('vp-ic-vol');
  var icMuted = document.getElementById('vp-ic-muted');
  var volEl   = document.getElementById('vp-vol');
  var rateBtn = document.getElementById('vp-rate');
  var fsBtn   = document.getElementById('vp-fs');
  var icMax   = document.getElementById('vp-ic-max');
  var icMin   = document.getElementById('vp-ic-min');
  var poster  = document.getElementById('vp-poster');
  var endOv   = document.getElementById('vp-end');
  var replay  = document.getElementById('vp-replay');
  var spinner = document.getElementById('vp-spinner');

  var player = null;
  var ready = false;        // onReady fired for the current player instance
  var pendingPlay = false;  // play was requested before the player was ready
  var playIntent = false;   // last user/state intent: true = should be playing
  var intentAt = 0;         // when the user last explicitly played/paused
  var lastT = -1;           // getCurrentTime() at the previous tick
  var lastMoveAt = 0;       // wall-clock ms when the playback clock last moved
  var moving = false;       // clock moved within the sticky window → really playing
  var duration = 0;
  var ticker = null;
  var idleTimer = null;
  var dragging = false;

  // While a fresh user action settles, the UI follows the user, not YT.
  // MOVE_STICKY_MS must stay below INTENT_GRACE_MS: after an explicit pause
  // the stickiness has to expire before evidence is allowed to override.
  var INTENT_GRACE_MS = 3000;
  var MOVE_STICKY_MS = 2500;

  var RATES = [1, 1.25, 1.5, 1.75, 2, 0.75];

  function fmt(t) {
    t = Math.max(0, Math.floor(t || 0));
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    var mm = (h ? String(m).padStart(2, '0') : m);
    return (h ? h + ':' : '') + mm + ':' + String(s).padStart(2, '0');
  }

  function state() { return player && player.getPlayerState ? player.getPlayerState() : -1; }
  function isPlaying() { return state() === 1; }
  // "Playing-ish": actually playing (per state cache OR the moving clock),
  // buffering on the way to playing, or queued.
  function playingish() {
    return pendingPlay || isPlaying() || moving || (state() === 3 && playIntent);
  }

  // ── Buffering / loading spinner ─────────────────────────
  function setSpinner(on) {
    if (spinner) spinner.hidden = !on;
    shell.classList.toggle('vp-loading', on);
  }

  // ── Progress / time readout ─────────────────────────────
  function paint() {
    if (!player || !player.getCurrentTime) return;
    var t = player.getCurrentTime() || 0;
    var d = player.getDuration ? (player.getDuration() || 0) : 0;
    if (d > 0 && d !== duration) {
      duration = d;
      seekEl.max = d;
    }
    if (!dragging) {
      seekEl.value = t;
      seekEl.style.setProperty('--vp-progress', (duration ? (t / duration * 100) : 0) + '%');
    }
    timeEl.textContent = fmt(dragging ? Number(seekEl.value) : t) + ' / ' + fmt(duration);
    // The icon follows playIntent, and playIntent only changes on solid
    // evidence — never on YT's state cache alone. On slow networks both the
    // cache (getPlayerState) and the time updates arrive late and in bursts:
    // the cache can claim "paused" for many seconds while the video is
    // visibly playing. So: a clock that moved organically within the sticky
    // window means "playing" (bursty updates can't fake a freeze); a clock
    // frozen past the window WITH the cache agreeing on paused/ended means
    // "paused". A fresh user action gets INTENT_GRACE_MS before any override.
    var now = Date.now();
    var dt = lastT >= 0 ? t - lastT : 0;
    if (dt > 0.01 && dt < 1.5) lastMoveAt = now;  // organic motion; seeks jump farther
    lastT = t;
    moving = now - lastMoveAt < MOVE_STICKY_MS;
    var s = state();
    if (now - intentAt > INTENT_GRACE_MS) {
      if (!playIntent && moving) playIntent = true;
      else if (playIntent && !moving && (s === 2 || s === 0 || s === 5)) playIntent = false;
    }
    paintPlayIcon(playIntent || pendingPlay);
    if (!pendingPlay) setSpinner(s === 3 && !moving);
  }

  // Runs from onReady onward and never stops — paused repaints are cheap,
  // and a ticker that only runs while playing is dead exactly when the UI
  // has drifted out of sync.
  function startTicker() {
    if (ticker) return;
    ticker = setInterval(paint, 250);
  }

  // ── Idle auto-hide of the control bar ───────────────────
  function wake() {
    shell.classList.remove('vp-idle');
    if (idleTimer) clearTimeout(idleTimer);
    if (isPlaying() || moving) {
      idleTimer = setTimeout(function () { shell.classList.add('vp-idle'); }, 2600);
    }
  }
  shell.addEventListener('mousemove', wake);
  shell.addEventListener('touchstart', wake, { passive: true });
  bar.addEventListener('mousemove', function (e) { e.stopPropagation(); wake(); });

  // ── Play / pause ────────────────────────────────────────
  function paintPlayIcon(playing) {
    icPlay.hidden = playing;
    icPause.hidden = !playing;
  }
  function play() {
    playIntent = true;
    intentAt = Date.now();
    if (!player || !ready) {
      // Player still bootstrapping (slow network): queue the intent instead of
      // dropping the click, and show the spinner so the tap visibly "took".
      pendingPlay = true;
      setSpinner(true);
      paintPlayIcon(true);
      return;
    }
    if (state() === 0) player.seekTo(0, true);
    player.playVideo();
    paintPlayIcon(true);   // optimistic; the state event confirms
  }
  function pause() {
    playIntent = false;
    intentAt = Date.now();
    pendingPlay = false;
    setSpinner(false);
    paintPlayIcon(false);
    if (player && ready) player.pauseVideo();
  }
  function toggle() { playingish() ? pause() : play(); }

  playBtn.addEventListener('click', toggle);

  // Single click toggles immediately (like youtube.com); a double click also
  // goes fullscreen — its two click events cancel each other out, so the only
  // cost is a brief pause/resume flicker.
  gesture.addEventListener('click', function () {
    var touch = window.matchMedia('(hover: none)').matches;
    if (touch && shell.classList.contains('vp-idle')) { wake(); return; }
    toggle();
  });
  gesture.addEventListener('dblclick', toggleFs);

  // ── Poster (pre-play cover) ─────────────────────────────
  function hidePoster() {
    if (poster) { poster.remove(); poster = null; }
  }
  if (poster) poster.addEventListener('click', play);

  // ── End screen ──────────────────────────────────────────
  if (replay) {
    replay.addEventListener('click', function () {
      endOv.hidden = true;
      play();
    });
  }

  // ── Seek ────────────────────────────────────────────────
  seekEl.addEventListener('input', function () {
    dragging = true;
    seekEl.style.setProperty('--vp-progress', (duration ? (seekEl.value / duration * 100) : 0) + '%');
    timeEl.textContent = fmt(Number(seekEl.value)) + ' / ' + fmt(duration);
  });
  seekEl.addEventListener('change', function () {
    dragging = false;
    if (player) player.seekTo(Number(seekEl.value), true);
    if (endOv && !endOv.hidden) endOv.hidden = true;
  });
  function relSeek(delta) {
    if (!player || !player.getCurrentTime) return;
    var t = Math.min(Math.max(0, player.getCurrentTime() + delta), duration || Infinity);
    player.seekTo(t, true);
    paint();
    wake();
  }

  // ── Volume / mute ───────────────────────────────────────
  function paintVolume() {
    if (!player || !player.isMuted) return;
    var muted = player.isMuted() || Number(volEl.value) === 0;
    icVol.hidden = muted;
    icMuted.hidden = !muted;
    volEl.style.setProperty('--vp-progress', (muted ? 0 : volEl.value) + '%');
  }
  function toggleMute() {
    if (!player) return;
    if (player.isMuted()) { player.unMute(); localStorage.setItem('vp:muted', '0'); }
    else { player.mute(); localStorage.setItem('vp:muted', '1'); }
    setTimeout(paintVolume, 60);
  }
  muteBtn.addEventListener('click', toggleMute);
  volEl.addEventListener('input', function () {
    if (!player) return;
    player.setVolume(Number(volEl.value));
    if (Number(volEl.value) > 0 && player.isMuted()) player.unMute();
    localStorage.setItem('vp:vol', volEl.value);
    localStorage.setItem('vp:muted', '0');
    paintVolume();
  });

  // ── Playback rate ───────────────────────────────────────
  function applyRate(r) {
    if (player && player.setPlaybackRate) player.setPlaybackRate(r);
    rateBtn.textContent = (r % 1 === 0 ? r : r.toFixed(2).replace(/0$/, '')) + '×';
    localStorage.setItem('vp:rate', String(r));
  }
  rateBtn.addEventListener('click', function () {
    var cur = player && player.getPlaybackRate ? player.getPlaybackRate() : 1;
    var i = RATES.indexOf(cur);
    applyRate(RATES[(i + 1) % RATES.length]);
  });

  // ── Fullscreen (wrapper-level, so our controls stay) ────
  function nativeFsEl() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }
  function inFs() {
    return nativeFsEl() === shell || shell.classList.contains('vp-fs-fallback');
  }
  function toggleFs() {
    if (inFs()) {
      if (nativeFsEl()) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      else shell.classList.remove('vp-fs-fallback');
    } else {
      if (shell.requestFullscreen) shell.requestFullscreen();
      else if (shell.webkitRequestFullscreen) shell.webkitRequestFullscreen();
      else shell.classList.add('vp-fs-fallback');  // iOS Safari
    }
    paintFs();
  }
  function paintFs() {
    var fs = inFs();
    icMax.hidden = fs;
    icMin.hidden = !fs;
  }
  fsBtn.addEventListener('click', toggleFs);
  document.addEventListener('fullscreenchange', paintFs);
  document.addEventListener('webkitfullscreenchange', paintFs);

  // ── Keyboard shortcuts ──────────────────────────────────
  document.addEventListener('keydown', function (e) {
    if (!player || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target;
    if (t && t.closest) {
      // never hijack typing, and let focused page controls outside the player
      // keep their native key behavior
      if (t.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (t.closest('button, a') && !t.closest('.vp')) return;
    }
    var key = e.key.toLowerCase();
    if (key === ' ' || key === 'k') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); relSeek(-5); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); relSeek(5); }
    else if (key === 'm') { toggleMute(); }
    else if (key === 'f') { toggleFs(); }
  });

  // ── Wire up the player instance (created by lesson_tracker.js) ──
  function onReady() {
    ready = true;
    var vol = localStorage.getItem('vp:vol');
    if (vol !== null) { player.setVolume(Number(vol)); volEl.value = vol; }
    if (localStorage.getItem('vp:muted') === '1') player.mute();
    var rate = parseFloat(localStorage.getItem('vp:rate'));
    if (rate && RATES.indexOf(rate) !== -1) applyRate(rate);
    if (pendingPlay) {
      pendingPlay = false;
      play();
    }
    startTicker();  // the ticker reconciles icon/spinner/time from here on
    paint();
    paintVolume();
  }

  function onState(e) {
    if (e.data === 1) {            // PLAYING — a real event is solid evidence
      playIntent = true;
      hidePoster();
      if (endOv) endOv.hidden = true;
      startTicker();
    } else if (e.data === 2 || e.data === 0) {  // PAUSED / ENDED
      // Trust the event unless it's a stale straggler racing a fresh play.
      if (Date.now() - intentAt > 1500) playIntent = false;
      if (e.data === 0 && endOv) endOv.hidden = false;
    }
    paint();  // repaints icon/spinner and updates the motion tracker
    wake();
  }

  window.__vpSetPlayer = function (p) {
    player = p;
    p.addEventListener('onReady', onReady);
    p.addEventListener('onStateChange', onState);
    // onReady may already have fired before we attached; apply prefs anyway.
    if (p.getPlayerState && p.getPlayerState() !== undefined && p.setVolume) onReady();
  };
})();

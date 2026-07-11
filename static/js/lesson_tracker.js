(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('lesson-config').textContent);
  var IS_AUTH      = cfg.is_authenticated;
  var IS_ARTICLE   = cfg.is_article;
  var VIDEO_ID     = cfg.video_id;
  var URL_RECORD   = cfg.url_record;
  var URL_COMPLETE = cfg.url_complete;
  var CSRF         = cfg.csrf_token;

  // Fraction of the video that counts as "watched" → auto-complete.
  var COMPLETE_RATIO = 0.9;

  var recorded = false;
  var completed = !!cfg.is_completed;  // already done? don't re-complete.
  var player = null;
  var pollTimer = null;

  var completeBtn = document.getElementById('btn-complete');

  // ── A view: enroll + streak + activity. NOT completion. ──
  function recordView() {
    if (recorded || !IS_AUTH) return;
    recorded = true;
    fetch(URL_RECORD, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
      body: '{}',
      keepalive: true,
    }).catch(function () { recorded = false; });
  }

  // ── Completion: video watched to ~90%/end, or the manual button. ──
  // `reload` is true only for the explicit button click; the auto-complete
  // updates the button in place so it never interrupts playback.
  function markComplete(reload) {
    if (completed || !IS_AUTH) return;
    completed = true;
    if (completeBtn) completeBtn.disabled = true;
    fetch(URL_COMPLETE, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF },
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        if (data && data.is_completed) {
          if (reload) window.location.reload();
          else markButtonDone();
        } else {
          completed = false;
          if (completeBtn) completeBtn.disabled = false;
        }
      })
      .catch(function () {
        completed = false;
        if (completeBtn) completeBtn.disabled = false;
      });
  }

  function markButtonDone() {
    if (!completeBtn) return;
    completeBtn.textContent = 'Dars tugatildi';
    completeBtn.classList.add('btn-done');
    completeBtn.disabled = true;
  }

  if (completeBtn) {
    completeBtn.addEventListener('click', function () { markComplete(true); });
  }

  // ── Article lessons: record a view on load (no player, no auto-complete). ──
  if (IS_ARTICLE) {
    if (IS_AUTH) recordView();
    return;
  }

  // ── Poll playback position; auto-complete once past the threshold. ──
  function startPoll() {
    if (pollTimer || completed || !IS_AUTH) return;
    pollTimer = setInterval(function () {
      if (completed) { clearInterval(pollTimer); pollTimer = null; return; }
      try {
        var d = player && player.getDuration ? player.getDuration() : 0;
        var t = player && player.getCurrentTime ? player.getCurrentTime() : 0;
        if (d > 0 && (t / d) >= COMPLETE_RATIO) {
          clearInterval(pollTimer); pollTimer = null;
          markComplete(false);
        }
      } catch (e) {}
    }, 5000);
  }

  // ── YouTube IFrame API ──────────────────────────────────
  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('yt-player', {
      videoId: VIDEO_ID,
      // controls:0 — native chrome off; our own bar (lesson_player.js) drives
      // the player through the API, so YouTube's title/gradient overlay never
      // renders on pause (it only appears with native controls or iframe hover).
      playerVars: { rel: 0, controls: 0, disablekb: 1, playsinline: 1, iv_load_policy: 3, fs: 0 },
      events: {
        onStateChange: function (e) {
          if (e.data === YT.PlayerState.PLAYING) {
            recordView();
            startPoll();
          } else if (e.data === YT.PlayerState.ENDED) {
            markComplete(false);
          }
        },
      },
    });
    // Expose player reference for bookmark + custom-controls JS
    if (window.__bmSetPlayer) window.__bmSetPlayer(player);
    if (window.__vpSetPlayer) window.__vpSetPlayer(player);
  };

  // ── Inject the IFrame API script ────────────────────────
  if (!window.YT) {
    var tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
  } else {
    window.onYouTubeIframeAPIReady();
  }
})();

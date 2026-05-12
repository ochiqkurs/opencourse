(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('lesson-config').textContent);
  var IS_AUTH      = cfg.is_authenticated;
  var VIDEO_ID     = cfg.video_id;
  var URL_RECORD   = cfg.url_record;
  var URL_COMPLETE = cfg.url_complete;
  var CSRF         = cfg.csrf_token;

  var recorded = false;

  // ── YouTube IFrame API ──────────────────────────────────
  // Only used to detect "play started" so we can fire one POST and (server-side)
  // record a daily LessonView + mark progress complete. No seek/heartbeat/beacon.
  window.onYouTubeIframeAPIReady = function () {
    new YT.Player('yt-player', {
      videoId: VIDEO_ID,
      playerVars: { rel: 0, modestbranding: 1 },
      events: {
        onStateChange: function (e) {
          if (e.data === YT.PlayerState.PLAYING) recordView();
        },
      },
    });
  };

  function recordView() {
    if (recorded || !IS_AUTH) return;
    recorded = true;
    fetch(URL_RECORD, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
      body: '{}',
      keepalive: true,
    }).catch(function () { recorded = false; });  // allow retry on next play
  }

  // ── Manual "mark complete" button ───────────────────────
  var completeBtn = document.getElementById('btn-complete');
  if (completeBtn) {
    completeBtn.addEventListener('click', function () {
      completeBtn.disabled = true;
      fetch(URL_COMPLETE, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF },
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.is_completed) window.location.reload();
        })
        .catch(function () { completeBtn.disabled = false; });
    });
  }

  // ── Inject the IFrame API script ────────────────────────
  if (!window.YT) {
    var tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
  } else {
    window.onYouTubeIframeAPIReady();
  }
})();

(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('lesson-config').textContent);
  var IS_AUTH      = cfg.is_authenticated;
  var IS_ARTICLE   = cfg.is_article;
  var VIDEO_ID     = cfg.video_id;
  var URL_RECORD   = cfg.url_record;
  var URL_COMPLETE = cfg.url_complete;
  var CSRF         = cfg.csrf_token;

  var recorded = false;

  // ── Article lessons: auto-record view on page load ──────
  if (IS_ARTICLE) {
    if (IS_AUTH) recordView();
    return;  // No YouTube player needed
  }

  // ── YouTube IFrame API ──────────────────────────────────
  window.onYouTubeIframeAPIReady = function () {
    var player = new YT.Player('yt-player', {
      videoId: VIDEO_ID,
      playerVars: { rel: 0, modestbranding: 1 },
      events: {
        onStateChange: function (e) {
          if (e.data === YT.PlayerState.PLAYING) recordView();
        },
      },
    });
    // Expose player reference for bookmark JS
    if (window.__bmSetPlayer) window.__bmSetPlayer(player);
  };

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

  // ── Manual "mark complete" button ───────────────────────
  var completeBtn = document.getElementById('btn-complete');
  if (completeBtn) {
    completeBtn.addEventListener('click', function () {
      completeBtn.disabled = true;
      fetch(URL_COMPLETE, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF },
      })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) {
          if (data && data.is_completed) window.location.reload();
          else completeBtn.disabled = false;
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

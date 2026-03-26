(function () {
  'use strict';

  var config = JSON.parse(document.getElementById('lesson-config').textContent);
  var LESSON_ID   = config.lesson_id;
  var VIDEO_ID    = config.video_id;
  var CSRF        = config.csrf_token;
  var URL_START   = config.url_start;
  var URL_EVENT   = config.url_event;
  var URL_BEACON  = config.url_beacon;
  var URL_COMPLETE = config.url_complete;
  var IS_AUTH     = config.is_authenticated;
  var SESSION_KEY = 'session_' + LESSON_ID;

  var player, sessionId, heartbeatTimer;
  var pauseTime = null;

  // ── Toast notifications ──────────────────────────────────────────────
  function showToast(message, type) {
    var existing = document.getElementById('lesson-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.id = 'lesson-toast';
    toast.className = 'lesson-toast lesson-toast-' + (type || 'info');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 4000);
  }

  // ── YouTube IFrame API ───────────────────────────────────────────────
  var ytReady = false;
  var ytTimeout = setTimeout(function () {
    if (!ytReady) console.warn('YouTube IFrame API did not fire within 5 s');
  }, 5000);

  window.onYouTubeIframeAPIReady = function () {
    ytReady = true;
    clearTimeout(ytTimeout);
    player = new YT.Player('yt-player', {
      videoId: VIDEO_ID,
      playerVars: { rel: 0 },
      events: {
        onReady: onPlayerReady,
        onStateChange: IS_AUTH ? onStateChange : undefined,
        onPlaybackRateChange: IS_AUTH ? onRateChange : undefined,
      },
    });
  };

  function onPlayerReady() {
    if (!IS_AUTH) return;
    var duration = player.getDuration();
    sessionId = sessionStorage.getItem(SESSION_KEY);
    if (sessionId) return;
    fetch(URL_START, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ duration_seconds: Math.round(duration) }),
    })

    .then(function (r) {
      if (!r.ok) {
        if (r.status === 403) {
          showToast('Sessiya tugagan. Sahifani yangilang', 'error');
          return Promise.reject('forbidden');
        }
        return r.text().then(function (t) { return Promise.reject('HTTP ' + r.status + ': ' + t.substring(0, 200)); });
      }
      return r.json();
    })
    .then(function (d) {
      if (!d) return;
      sessionId = d.session_id;
      sessionStorage.setItem(SESSION_KEY, sessionId);
      sessionStorage.setItem(SESSION_KEY + '_ts', Date.now());
    })
    .catch(function (err) {
      console.error('session_start failed:', err);
      if (err !== 'forbidden') {
        showToast('Video kuzatuvi ishlamayapti', 'error');
      }
    });
  }

  // ── Event sending ────────────────────────────────────────────────────
  function sendEvent(type, position, metadata) {
    if (!sessionId) return;
    fetch(URL_EVENT, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        session_id: sessionId,
        event_type: type,
        position_seconds: Math.round(position),
        metadata: metadata || {},
      }),
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.auto_completed) markCompletedInUI();
    })
    .catch(function () { /* silent for events */ });
  }

  function onStateChange(event) {
    var t = player.getCurrentTime();
    if (event.data === YT.PlayerState.PLAYING) {
      if (pauseTime !== null && Math.abs(t - pauseTime) > 2) {
        sendEvent('seek', pauseTime, { seek_to: Math.round(t) });
      }
      pauseTime = null;
      sendEvent('play', t, {});
      clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(function () {
        if (player.getPlayerState() === YT.PlayerState.PLAYING) {
          sendEvent('heartbeat', player.getCurrentTime(), {});
        }
      }, 30000);
    } else if (event.data === YT.PlayerState.PAUSED) {
      pauseTime = t;
      clearInterval(heartbeatTimer);
      sendEvent('pause', t, {});
    } else if (event.data === YT.PlayerState.ENDED) {
      pauseTime = null;
      clearInterval(heartbeatTimer);
      sendEvent('ended', t, {});
    }
  }

  function onRateChange(event) {
    if (!sessionId) return;
    sendEvent('speed_change', player.getCurrentTime(), { playback_rate: event.data });
  }

  // ── Visibility change (session management) ──────────────────────────
  if (IS_AUTH) {
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') {
        if (!sessionId) return;
        clearInterval(heartbeatTimer);
        var pos = player ? Math.round(player.getCurrentTime()) : 0;
        var payload = JSON.stringify({
          session_id: sessionId,
          event_type: 'page_hidden',
          position_seconds: pos,
          metadata: {},
        });
        navigator.sendBeacon(URL_BEACON, new Blob([payload], { type: 'application/json' }));
        sessionStorage.setItem(SESSION_KEY + '_ts', Date.now());
      } else if (document.visibilityState === 'visible') {
        var ts = parseInt(sessionStorage.getItem(SESSION_KEY + '_ts') || '0', 10);
        var elapsedMin = (Date.now() - ts) / 60000;
        if (elapsedMin > 30) {
          sessionStorage.removeItem(SESSION_KEY);
          sessionStorage.removeItem(SESSION_KEY + '_ts');
          sessionId = null;
          if (player) {
            var dur = player.getDuration();
            fetch(URL_START, {
              method: 'POST',
              headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
              credentials: 'same-origin',
              body: JSON.stringify({ duration_seconds: Math.round(dur) }),
            })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              sessionId = d.session_id;
              sessionStorage.setItem(SESSION_KEY, sessionId);
              sessionStorage.setItem(SESSION_KEY + '_ts', Date.now());
            })
            .catch(function () {});
          }
        }
      }
    });
  }

  // ── Mark complete button ─────────────────────────────────────────────
  var btnComplete = document.getElementById('btn-complete');
  if (btnComplete) {
    btnComplete.addEventListener('click', function () {
      btnComplete.disabled = true;
      btnComplete.textContent = 'Yuklanmoqda...';
      fetch(URL_COMPLETE, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
        credentials: 'same-origin',
      })
      .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
      .then(function (result) {
        if (result.ok && result.data.status === 'ok') {
          markCompletedInUI();
        } else if (result.data.error === 'not_enough_watched') {
          var mins = Math.ceil(result.data.required_seconds / 60);
          showToast('Kamida ' + mins + ' daqiqa tomosha qiling', 'warning');
          btnComplete.disabled = false;
          btnComplete.textContent = 'Tugatilgan deb belgilash';
        } else {
          showToast('Xatolik yuz berdi', 'error');
          btnComplete.disabled = false;
          btnComplete.textContent = 'Tugatilgan deb belgilash';
        }
      })
      .catch(function () {
        showToast('Tarmoq xatosi', 'error');
        btnComplete.disabled = false;
        btnComplete.textContent = 'Tugatilgan deb belgilash';
      });
    });
  }

  function markCompletedInUI() {
    var btn = document.getElementById('btn-complete');
    if (btn) {
      var badge = document.createElement('p');
      badge.className = 'completed-badge';
      badge.textContent = '\u2713 Completed';
      btn.parentNode.replaceChild(badge, btn);
    }
  }

  // ── Load YouTube IFrame API ──────────────────────────────────────────
  var tag = document.createElement('script');
  tag.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(tag);
}());

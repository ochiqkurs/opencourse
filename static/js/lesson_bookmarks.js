(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('lesson-config').textContent);
  var CSRF = cfg.csrf_token;
  var URL_SAVE = cfg.url_save_bookmark;
  if (!URL_SAVE) return;

  var player = null;
  window.__bmSetPlayer = function (p) { player = p; };

  // ── Add bookmark: capture current time ──────────────────
  var addBtn = document.getElementById('bm-add-btn');
  var noteForm = document.getElementById('bm-note-form');
  var noteInput = document.getElementById('bm-note-input');
  var saveBtn = document.getElementById('bm-save-btn');
  var cancelBtn = document.getElementById('bm-cancel-btn');

  if (addBtn) {
    addBtn.addEventListener('click', function () {
      var seconds = 0;
      if (player && typeof player.getCurrentTime === 'function') {
        seconds = Math.floor(player.getCurrentTime());
      }
      noteForm.dataset.seconds = seconds;
      noteForm.classList.remove('hidden');
      noteInput.value = '';
      noteInput.focus();
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener('click', function () {
      noteForm.classList.add('hidden');
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      var seconds = parseInt(noteForm.dataset.seconds, 10) || 0;
      var note = noteInput.value.trim();
      saveBtn.disabled = true;
      fetch(URL_SAVE, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
        body: JSON.stringify({ timestamp: seconds, note: note }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) {
          if (data.status === 'ok') {
            noteForm.classList.add('hidden');
            location.reload();
          } else {
            saveBtn.disabled = false;
          }
        })
        .catch(function () { saveBtn.disabled = false; });
    });
  }

  // ── Delete bookmark ─────────────────────────────────────
  document.querySelectorAll('.bm-delete').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var url = btn.dataset.url;
      if (!confirm("Xatcho'pni o'chirishni xohlaysizmi?")) return;
      fetch(url, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF },
      }).then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function () {
          var item = btn.closest('.bm-item');
          if (item) item.remove();
          var list = document.getElementById('bm-list');
          if (list && !list.querySelector('.bm-item')) {
            list.innerHTML = '<li class="bm-empty">Hozircha xatcho\'plar yo\'q.</li>';
          }
        })
        .catch(function () {});
    });
  });

  // ── Click bookmark → seek video ─────────────────────────
  document.querySelectorAll('.bm-timestamp').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var seconds = parseInt(btn.dataset.seconds, 10);
      if (player && typeof player.seekTo === 'function') {
        player.seekTo(seconds, true);
      }
      // Switch to video tab
      var descBtn = document.querySelector('.ld-tabs button[data-ld="desc"]');
      if (descBtn) descBtn.click();
    });
  });
})();

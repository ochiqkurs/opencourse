(function () {
  'use strict';

  // ── Note edit/preview toggle ─────────────────────────────────────────
  var btnEdit = document.getElementById('btn-edit-note');
  var noteEditor = document.getElementById('note-editor');
  var notePreview = document.getElementById('note-preview');
  if (btnEdit) {
    btnEdit.addEventListener('click', function () {
      notePreview.classList.add('note-hidden');
      btnEdit.classList.add('note-hidden');
      noteEditor.classList.remove('note-hidden');
      document.getElementById('note-content').focus();
    });
  }

  // ── Save note ────────────────────────────────────────────────────────
  var btnNote = document.getElementById('btn-save-note');
  var noteStatus = document.getElementById('note-status');
  if (btnNote) {
    var config = JSON.parse(document.getElementById('lesson-config').textContent);
    btnNote.addEventListener('click', function () {
      var content = document.getElementById('note-content').value;
      btnNote.disabled = true;
      fetch(btnNote.dataset.url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': config.csrf_token,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ content: content }),
      })
      .then(function (res) {
        if (!res.ok) throw new Error(res.status);
        return res.json();
      })
      .then(function (data) {
        btnNote.disabled = false;
        if (data.status === 'ok') {
          noteStatus.textContent = '\u2713 Saqlandi';
          noteStatus.className = 'note-status note-status-ok';
          if (notePreview && data.rendered !== undefined) {
            notePreview.innerHTML = data.rendered || '';
            notePreview.querySelectorAll('pre code').forEach(function (el) {
              if (typeof hljs !== 'undefined') hljs.highlightElement(el);
            });
          }
          setTimeout(function () {
            noteStatus.textContent = '';
            if (content.trim() && noteEditor && notePreview) {
              noteEditor.classList.add('note-hidden');
              notePreview.classList.remove('note-hidden');
              if (btnEdit) btnEdit.classList.remove('note-hidden');
            }
          }, 800);
        }
      })
      .catch(function () {
        btnNote.disabled = false;
        noteStatus.textContent = 'Xatolik! Qaytadan urinib ko\'ring';
        noteStatus.className = 'note-status note-status-error';
      });
    });
  }
}());

(function () {
  'use strict';

  var dock = document.getElementById('tutor-dock');
  if (!dock) return;

  var btnToggle = document.getElementById('tutor-toggle');
  var btnClose = document.getElementById('tutor-close');
  var input = document.getElementById('tutor-input');
  var btnSend = document.getElementById('tutor-send');
  var messagesEl = document.getElementById('tutor-messages');
  var typingEl = document.getElementById('tutor-typing');
  var introEl = document.getElementById('tutor-intro');

  var STORAGE_KEY = 'tutorDockOpen';

  function scrollToBottom() {
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ── dock ochish/yopish (holat darslar orasida saqlanadi) ──
  function setOpen(open, skipAnim) {
    if (skipAnim) {
      dock.classList.add('tutor-no-anim');
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { dock.classList.remove('tutor-no-anim'); });
      });
    }
    dock.classList.toggle('open', open);
    document.body.classList.toggle('tutor-open', open);
    if (btnToggle) btnToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    try { localStorage.setItem(STORAGE_KEY, open ? '1' : '0'); } catch (e) { /* private mode */ }
    if (open) {
      scrollToBottom();
      // restore paytida fokus tortib olinmaydi
      if (!skipAnim && input && window.matchMedia('(min-width: 768px)').matches) input.focus();
    }
  }

  if (btnToggle) {
    btnToggle.addEventListener('click', function () {
      setOpen(!dock.classList.contains('open'));
    });
  }
  if (btnClose) {
    btnClose.addEventListener('click', function () { setOpen(false); });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && dock.classList.contains('open')) setOpen(false);
  });

  var startOpen = false;
  try { startOpen = localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) { /* private mode */ }
  if (startOpen) setOpen(true, true);

  // ── chat (faqat login qilganlar uchun mavjud) ──
  if (!input || !btnSend || !messagesEl) return;

  var config = JSON.parse(document.getElementById('lesson-config').textContent);
  var busy = false;

  function appendUserMsg(text) {
    var el = document.createElement('div');
    el.className = 'tutor-msg tutor-msg-user';
    el.textContent = text;
    messagesEl.insertBefore(el, typingEl);
    scrollToBottom();
  }

  function appendAiMsg(html) {
    var el = document.createElement('div');
    el.className = 'tutor-msg tutor-msg-ai md-content';
    el.innerHTML = html;
    el.querySelectorAll('pre code').forEach(function (code) {
      if (typeof hljs !== 'undefined') hljs.highlightElement(code);
    });
    messagesEl.insertBefore(el, typingEl);
    scrollToBottom();
  }

  function appendErrorMsg(text) {
    var el = document.createElement('div');
    el.className = 'tutor-msg tutor-msg-error';
    el.textContent = text;
    messagesEl.insertBefore(el, typingEl);
    scrollToBottom();
  }

  function setBusy(state) {
    busy = state;
    btnSend.disabled = state;
    typingEl.classList.toggle('tutor-hidden', !state);
    if (state) scrollToBottom();
  }

  function send() {
    var text = input.value.trim();
    if (!text || busy) return;
    if (introEl) introEl.classList.add('tutor-hidden');
    appendUserMsg(text);
    input.value = '';
    setBusy(true);

    fetch(config.url_tutor, {
      method: 'POST',
      headers: {
        'X-CSRFToken': config.csrf_token,
        'Content-Type': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify({ message: text }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (r) {
        setBusy(false);
        if (r.ok && r.data.status === 'ok') {
          appendAiMsg(r.data.rendered || '');
        } else {
          appendErrorMsg(r.data.error || "Xatolik yuz berdi. Qayta urinib ko'ring.");
        }
        input.focus();
      })
      .catch(function () {
        setBusy(false);
        appendErrorMsg("Tarmoq xatosi. Qayta urinib ko'ring.");
      });
  }

  btnSend.addEventListener('click', send);
  input.addEventListener('keydown', function (e) {
    // Enter yuboradi, Shift+Enter yangi qator
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  scrollToBottom();
}());

/* Navbar live search suggestions */
(function () {
  'use strict';
  var input = document.getElementById('nav-search-input');
  var box = document.getElementById('nav-search-suggest');
  if (!input || !box) return;

  var url = input.dataset.suggestUrl || '/malaka/qidiruv/';
  var timer = null;
  var lastQuery = '';
  var lastFetch = null;

  function close() { box.classList.remove('open'); box.innerHTML = ''; }
  function open() { box.classList.add('open'); }

  function render(data, q) {
    var courses = (data.courses || []);
    var lessons = (data.lessons || []);
    if (!courses.length && !lessons.length) {
      box.innerHTML = '<div class="ss-empty">"' + escapeHtml(q) + '" bo\'yicha hech narsa topilmadi</div>';
      open();
      return;
    }
    var html = '';
    if (courses.length) {
      html += '<div class="ss-group">Kurslar</div>';
      courses.forEach(function (c) {
        html +=
          '<a class="ss-item" href="' + c.url + '">' +
            (c.thumb ? '<img class="ss-thumb" src="' + c.thumb + '" alt="">' : '<span class="ss-thumb"></span>') +
            '<div>' +
              '<div>' + escapeHtml(c.title) + '</div>' +
              (c.category ? '<div class="ss-meta">' + escapeHtml(c.category) + '</div>' : '') +
            '</div>' +
          '</a>';
      });
    }
    if (lessons.length) {
      html += '<div class="ss-group">Darslar</div>';
      lessons.forEach(function (l) {
        html +=
          '<a class="ss-item" href="' + l.url + '">' +
            '<span class="ss-thumb"></span>' +
            '<div>' +
              '<div>' + escapeHtml(l.title) + '</div>' +
              '<div class="ss-meta">' + escapeHtml(l.course) + '</div>' +
            '</div>' +
          '</a>';
      });
    }
    box.innerHTML = html;
    open();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }

  function fetchSuggest(q) {
    if (lastFetch && lastFetch.abort) try { lastFetch.abort(); } catch (e) {}
    var ctrl = new AbortController();
    lastFetch = ctrl;
    fetch(url + '?q=' + encodeURIComponent(q) + '&format=json', { signal: ctrl.signal })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (q !== input.value.trim()) return;
        render(data, q);
      })
      .catch(function () {});
  }

  input.addEventListener('input', function () {
    var q = input.value.trim();
    if (q === lastQuery) return;
    lastQuery = q;
    clearTimeout(timer);
    if (q.length < 2) { close(); return; }
    timer = setTimeout(function () { fetchSuggest(q); }, 220);
  });

  input.addEventListener('focus', function () {
    if (input.value.trim().length >= 2 && box.innerHTML) open();
  });

  document.addEventListener('click', function (e) {
    if (!box.contains(e.target) && e.target !== input) close();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { close(); input.blur(); }
  });
})();

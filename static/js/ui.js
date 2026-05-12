/* UI interactions: theme toggle, user dropdown, mobile drawer */
(function () {
  'use strict';

  // ── Theme toggle ─────────────────────────────────────────
  var btn = document.getElementById('theme-toggle');
  var iconLight = btn && btn.querySelector('.theme-icon-light');
  var iconDark = btn && btn.querySelector('.theme-icon-dark');

  function syncThemeIcons() {
    var current = document.documentElement.getAttribute('data-theme');
    var isDark = current === 'dark' ||
      (!current && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (iconLight && iconDark) {
      iconLight.classList.toggle('hidden', isDark);
      iconDark.classList.toggle('hidden', !isDark);
    }
  }
  syncThemeIcons();

  if (btn) {
    btn.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme');
      var isDark = current === 'dark' ||
        (!current && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
      var next = isDark ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
      syncThemeIcons();
    });
  }

  // ── User dropdown ────────────────────────────────────────
  var userWrap = document.getElementById('nav-user');
  var userTrigger = document.getElementById('nav-user-trigger');
  if (userWrap && userTrigger) {
    userTrigger.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = userWrap.classList.toggle('open');
      userTrigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', function (e) {
      if (userWrap.classList.contains('open') && !userWrap.contains(e.target)) {
        userWrap.classList.remove('open');
        userTrigger.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        userWrap.classList.remove('open');
        userTrigger.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // ── Mobile drawer ────────────────────────────────────────
  var mobileBtn = document.getElementById('mobile-toggle');
  var drawer = document.getElementById('mobile-drawer');
  if (mobileBtn && drawer) {
    mobileBtn.addEventListener('click', function () {
      drawer.classList.toggle('open');
    });
    // Close on link click
    drawer.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        drawer.classList.remove('open');
      });
    });
  }
})();

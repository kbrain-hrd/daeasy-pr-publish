/*
 * 보관본 안내 띠.
 *
 * 원본에서 AI 가 그때그때 만들어내던 기능은 보관본에서 동작하지 않는다.
 * 방문자가 개발자 에러 메시지를 보고 고장난 줄 알지 않도록,
 * 무엇이 보관본이고 무엇이 안 되는지 화면 아래에 짧게 알린다.
 *
 * 문구는 sites.json 의 notice 값에서 온다 (inject.py 가 넣는다).
 */
(function () {
  'use strict';

  var text = window.__ARCHIVE_NOTICE__;
  if (!text) return;

  function mount() {
    if (document.getElementById('archive-notice')) return;

    var bar = document.createElement('div');
    bar.id = 'archive-notice';
    bar.setAttribute('role', 'note');
    bar.style.cssText = [
      'position:fixed', 'left:12px', 'bottom:12px', 'z-index:2147483000',
      'max-width:min(420px, calc(100vw - 24px))',
      'display:flex', 'gap:10px', 'align-items:flex-start',
      'padding:10px 12px', 'border-radius:8px',
      'background:rgba(17,24,28,.92)', 'color:#e9eef1',
      'border:1px solid rgba(255,255,255,.14)',
      'box-shadow:0 6px 24px -8px rgba(0,0,0,.6)',
      'font:400 12px/1.5 "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif',
      'letter-spacing:-.01em'
    ].join(';');

    var body = document.createElement('div');
    body.style.cssText = 'flex:1';
    body.textContent = text;

    var close = document.createElement('button');
    close.type = 'button';
    close.textContent = '✕';
    close.setAttribute('aria-label', '안내 닫기');
    close.style.cssText = [
      'flex:none', 'background:none', 'border:0', 'color:inherit',
      'opacity:.6', 'cursor:pointer', 'font-size:12px',
      'padding:0 2px', 'line-height:1.5'
    ].join(';');
    close.addEventListener('click', function () { bar.remove(); });

    bar.appendChild(body);
    bar.appendChild(close);
    document.body.appendChild(bar);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();

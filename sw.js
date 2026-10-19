/* =====================================================================
   sw.js — 바탕화면 아이콘 설치를 위한 "작동 파일" (서비스 워커)
   ---------------------------------------------------------------------
   · 휴대폰(크롬)은 이 파일이 있어야 "바탕화면에 아이콘 설치"를 허락합니다.
   · 하는 일: 소식지 화면을 열 때마다 항상 인터넷에서 '최신 내용'을 먼저 받아 옵니다.
             인터넷이 끊겼을 때만, 마지막으로 받아 둔 화면을 대신 보여 줍니다.
     → 그래서 index.html 을 고쳐 올리면 교인들 휴대폰에도 바로 새 내용이 나옵니다.
   · 구글 시트, 주간충현 웹진 같은 '다른 사이트'의 내용은 건드리지 않습니다.
   ★ 이 파일은 수정할 일이 거의 없습니다. 고장 나기 쉬우니 그대로 두세요.
   ===================================================================== */

var CACHE_NAME = "n1-pages-v1"; /* 휴대폰에 화면을 보관해 두는 상자 이름 — 수정 금지 */

/* ① 설치될 때: 기다리지 않고 바로 일을 시작합니다 — 수정 금지 */
self.addEventListener("install", function () {
  self.skipWaiting();
});

/* ② 켜질 때: 예전 이름의 보관 상자가 있으면 지우고, 열려 있는 화면을 바로 맡습니다 — 수정 금지 */
self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.filter(function (n) { return n !== CACHE_NAME; })
                              .map(function (n) { return caches.delete(n); }));
    }).then(function () { return self.clients.claim(); })
  );
});

/* ③ 화면을 열 때: 인터넷 먼저 → 실패하면 보관해 둔 화면 — 수정 금지 */
self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;                                   /* 읽기 요청만 다룹니다 */
  if (new URL(req.url).origin !== self.location.origin) return;       /* 다른 사이트(구글 시트 등)는 그냥 통과 */
  if (req.mode !== "navigate") return;                                /* 화면(페이지) 열기만 다루고, 그림 등은 그냥 통과 */
  e.respondWith(
    fetch(req).then(function (res) {                                  /* 1) 인터넷에서 최신 화면 받기 */
      var copy = res.clone();
      caches.open(CACHE_NAME).then(function (c) { c.put(req, copy); }); /*    받은 화면을 보관 (다음 번 인터넷 끊김 대비) */
      return res;
    }).catch(function () {                                            /* 2) 인터넷이 안 되면 */
      return caches.match(req).then(function (r) {                    /*    보관해 둔 화면을 보여 줌 */
        return r || caches.match("./");                               /*    그 화면이 없으면 홈 화면이라도 */
      });
    })
  );
});

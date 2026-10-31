/* ============================================================
   保活：页面开着就每隔几秒报一次心跳；页面关闭时通知服务端。
   配合 server.py --exit-on-close 使用：关掉浏览器页面，服务自动停止。
   ============================================================ */
'use strict';

(function keepAlive() {
  const send = async () => {
    try {
      await fetch('/api/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ visible: document.visibilityState === 'visible' }),
        keepalive: true,
      });
    } catch (e) { /* 服务已停，忽略 */ }
  };

  send();
  // 5 秒一次；页面切到后台时浏览器会降频，所以服务端对"后台"用了更长的空闲上限
  const timer = setInterval(send, 5000);
  document.addEventListener('visibilitychange', send);

  const bye = () => {
    clearInterval(timer);
    try { navigator.sendBeacon('/api/client-closed', 'bye'); } catch (e) { /* ignore */ }
  };
  window.addEventListener('pagehide', bye);
  window.addEventListener('beforeunload', bye);
})();

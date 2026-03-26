/* ============================================
   FVFactory — WebSocket Manager
   ============================================ */

const FVWebSocket = (() => {
  let ws = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT = 10;
  const BASE_DELAY = 1000;
  const listeners = new Map();
  let connected = false;

  function getUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws`;
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

    try {
      ws = new WebSocket(getUrl());
    } catch (e) {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      connected = true;
      reconnectAttempts = 0;
      updateIndicator(true);
      emit('_connected', {});
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        emit(data.type, data);
        emit('_any', data);
      } catch (e) {
        console.warn('[WS] Bad message:', event.data);
      }
    };

    ws.onclose = () => {
      connected = false;
      updateIndicator(false);
      emit('_disconnected', {});
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will fire after this
    };
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) {
      console.warn('[WS] Max reconnection attempts reached');
      return;
    }
    const delay = Math.min(BASE_DELAY * Math.pow(2, reconnectAttempts), 30000);
    reconnectAttempts++;
    setTimeout(connect, delay);
  }

  function updateIndicator(isConnected) {
    const dot = document.getElementById('ws-indicator');
    const status = document.getElementById('ws-status');
    if (dot) {
      dot.className = isConnected ? 'topbar__dot' : 'topbar__dot topbar__dot--disconnected';
    }
    if (status) {
      status.textContent = isConnected ? 'Connected' : 'Reconnecting...';
    }
  }

  function on(type, callback) {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type).push(callback);
    return () => off(type, callback);
  }

  function off(type, callback) {
    const cbs = listeners.get(type);
    if (cbs) {
      const idx = cbs.indexOf(callback);
      if (idx >= 0) cbs.splice(idx, 1);
    }
  }

  function emit(type, data) {
    const cbs = listeners.get(type);
    if (cbs) cbs.forEach(cb => cb(data));
  }

  function isConnected() {
    return connected;
  }

  // Auto-connect on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', connect);
  } else {
    connect();
  }

  return { connect, on, off, isConnected };
})();

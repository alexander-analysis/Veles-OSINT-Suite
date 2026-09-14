import { useEffect, useRef, useState } from 'react';

/**
 * Auto-reconnecting WebSocket for the maritime stream.
 * `onMessage` receives parsed JSON frames; `status` is 'connecting' | 'open' | 'closed'.
 */
export function useWebSocket(path, onMessage) {
  const [status, setStatus] = useState('connecting');
  const [lastMessageAt, setLastMessageAt] = useState(null);
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (!path) return undefined;
    let socket;
    let timer;
    let closed = false;
    let delay = 2000;

    const connect = () => {
      const base = import.meta.env.VITE_API_BASE || '';
      const url = base
        ? base.replace(/^http/, 'ws') + path
        : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${path}`;
      setStatus('connecting');
      socket = new WebSocket(url);
      socket.onopen = () => {
        setStatus('open');
        delay = 2000;
      };
      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data);
          setLastMessageAt(new Date());
          handler.current?.(frame);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        setStatus('closed');
        if (!closed) {
          timer = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 30000);
        }
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [path]);

  return { status, lastMessageAt };
}

export default useWebSocket;

import { useState, useEffect, useRef, useCallback } from 'react';

function getDefaultWebSocketUrl() {
  if (typeof window === 'undefined') return 'ws://localhost:8000/ws';
  if (import.meta.env?.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}

export function useWebSocket(url) {
  const targetUrl = url || getDefaultWebSocketUrl();
  const [data, setData] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [reconnectCount, setReconnectCount] = useState(0);
  const [isStale, setIsStale] = useState(false);
  
  const ws = useRef(null);
  const reconnectTimeout = useRef(null);
  const pingInterval = useRef(null);
  const reconnectCountRef = useRef(0);
  const isUnmounted = useRef(false);

  // Periodically check if telemetry has stalled (>10 seconds without updates)
  useEffect(() => {
    const staleInterval = setInterval(() => {
      if (lastUpdate) {
        const elapsed = Date.now() - new Date(lastUpdate).getTime();
        setIsStale(elapsed > 10000 || !isConnected);
      } else {
        setIsStale(!isConnected);
      }
    }, 2000);
    return () => clearInterval(staleInterval);
  }, [lastUpdate, isConnected]);

  const connect = useCallback(() => {
    if (isUnmounted.current) return;
    try {
      if (ws.current && (ws.current.readyState === WebSocket.CONNECTING || ws.current.readyState === WebSocket.OPEN)) {
        return;
      }
      const socket = new WebSocket(targetUrl);
      ws.current = socket;

      socket.onopen = () => {
        if (isUnmounted.current || ws.current !== socket) return;
        setIsConnected(true);
        reconnectCountRef.current = 0;
        setReconnectCount(0);
        
        // Setup ping interval (20s)
        if (pingInterval.current) clearInterval(pingInterval.current);
        pingInterval.current = setInterval(() => {
          if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send('ping');
          }
        }, 20000);
      };

      socket.onmessage = (event) => {
        if (isUnmounted.current || ws.current !== socket || event.data === 'pong') return;
        try {
          const parsed = JSON.parse(event.data);
          // Accept explicit state_update, or payloads containing standard building snapshot
          if (parsed.type === 'state_update' || (parsed.building && parsed.metrics)) {
            setData(parsed);
            setLastUpdate(new Date());
            setIsStale(false);
          }
        } catch (err) {
          console.error('Error parsing WS message:', err);
        }
      };

      socket.onclose = () => {
        if (isUnmounted.current || ws.current !== socket) return;
        setIsConnected(false);
        if (pingInterval.current) clearInterval(pingInterval.current);
        
        // Reconnect with exponential backoff without recreating callback
        const count = reconnectCountRef.current;
        const timeout = Math.min(1000 * Math.pow(2, count), 30000);
        reconnectTimeout.current = setTimeout(() => {
          if (!isUnmounted.current) {
            reconnectCountRef.current += 1;
            setReconnectCount(reconnectCountRef.current);
            connect();
          }
        }, timeout);
      };

      socket.onerror = () => {
        socket.close();
      };
    } catch (error) {
      console.error('Error connecting to WebSocket:', error);
    }
  }, [targetUrl]);

  useEffect(() => {
    isUnmounted.current = false;
    connect();
    
    return () => {
      isUnmounted.current = true;
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      if (pingInterval.current) clearInterval(pingInterval.current);
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.onerror = null;
        ws.current.close();
        ws.current = null;
      }
    };
  }, [connect]);

  return { data, isConnected, isStale, lastUpdate, reconnectCount };
}

import { useState, useEffect, useRef, useCallback } from 'react';

export function useWebSocket(url = 'ws://localhost:8000/ws') {
  const [data, setData] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [reconnectCount, setReconnectCount] = useState(0);
  
  const ws = useRef(null);
  const reconnectTimeout = useRef(null);
  const pingInterval = useRef(null);

  const connect = useCallback(() => {
    try {
      ws.current = new WebSocket(url);

      ws.current.onopen = () => {
        setIsConnected(true);
        setReconnectCount(0);
        
        // Setup ping interval (20s)
        if (pingInterval.current) clearInterval(pingInterval.current);
        pingInterval.current = setInterval(() => {
          if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify({ type: 'ping' }));
          }
        }, 20000);
      };

      ws.current.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          if (parsed.type === 'state_update') {
            setData(parsed);
            setLastUpdate(new Date());
          }
        } catch (err) {
          console.error('Error parsing WS message:', err);
        }
      };

      ws.current.onclose = () => {
        setIsConnected(false);
        if (pingInterval.current) clearInterval(pingInterval.current);
        
        // Reconnect with exponential backoff
        const timeout = Math.min(1000 * Math.pow(2, reconnectCount), 30000);
        reconnectTimeout.current = setTimeout(() => {
          setReconnectCount(c => c + 1);
          connect();
        }, timeout);
      };

      ws.current.onerror = (error) => {
        console.error('WebSocket Error:', error);
        ws.current?.close();
      };
    } catch (error) {
      console.error('Error connecting to WebSocket:', error);
    }
  }, [url, reconnectCount]);

  useEffect(() => {
    connect();
    
    return () => {
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      if (pingInterval.current) clearInterval(pingInterval.current);
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [connect]);

  return { data, isConnected, lastUpdate, reconnectCount };
}

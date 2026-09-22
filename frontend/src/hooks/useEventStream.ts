import { useEffect, useRef, useState } from "react";

export interface LiveEvent {
  event_type: string;
  user_id: string;
  value: number;
  timestamp: string;
}

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8085";

export function useEventStream(maxEvents = 20) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const socket = new WebSocket(`${WS_URL}/api/v1/analytics/ws`);
    socketRef.current = socket;

    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (msg) => {
      const event: LiveEvent = JSON.parse(msg.data);
      setEvents((prev) => [event, ...prev].slice(0, maxEvents));
    };

    return () => socket.close();
  }, [maxEvents]);

  return { events, connected };
}

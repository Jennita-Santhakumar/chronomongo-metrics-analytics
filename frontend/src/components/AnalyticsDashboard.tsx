import React, { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { useEventStream } from "../hooks/useEventStream";
import "../styles/AnalyticsDashboard.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8085";

interface HourlyStat {
  _id: string;
  count: number;
  avg_value: number;
}

interface CohortData {
  retention: { _id: string; total_events: number }[];
  engagement: { _id: string | number; count: number }[];
}

export const AnalyticsDashboard: React.FC = () => {
  const [stats, setStats] = useState<HourlyStat[]>([]);
  const [percentiles, setPercentiles] = useState<Record<string, number>>({});
  const [cohortData, setCohortData] = useState<CohortData | null>(null);
  const [eventType, setEventType] = useState("page_view");
  const { events: liveEvents, connected } = useEventStream();

  useEffect(() => {
    const fetchStats = async () => {
      const res = await fetch(`${API_URL}/api/v1/analytics/hourly?event_type=${eventType}`);
      setStats(await res.json());

      const percRes = await fetch(`${API_URL}/api/v1/analytics/percentiles?event_type=${eventType}`);
      setPercentiles(await percRes.json());
    };
    fetchStats();
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [eventType]);

  useEffect(() => {
    const fetchCohort = async () => {
      const res = await fetch(`${API_URL}/api/v1/analytics/cohort`);
      setCohortData(await res.json());
    };
    fetchCohort();
  }, []);

  return (
    <div className="analytics-dashboard">
      <h1>Analytics Dashboard</h1>
      <p className="ws-status">
        Live stream: <span className={connected ? "on" : "off"}>{connected ? "connected" : "disconnected"}</span>
      </p>

      <div className="controls">
        <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
          <option value="page_view">Page View</option>
          <option value="click">Click</option>
          <option value="purchase">Purchase</option>
        </select>
      </div>

      <div className="charts-grid">
        <div className="chart-container">
          <h3>Hourly Trend</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={stats}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="_id" tick={{ fontSize: 10 }} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="count" stroke="#8884d8" />
              <Line type="monotone" dataKey="avg_value" stroke="#82ca9d" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-container">
          <h3>Value Distribution</h3>
          <div className="percentiles">
            {Object.entries(percentiles).map(([key, value]) => (
              <div key={key} className="percentile-row">
                <span>{key}</span>
                <span className="value">{value.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="chart-container">
          <h3>Engagement Distribution</h3>
          {cohortData?.engagement && (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={cohortData.engagement}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="_id" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#8884d8" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="chart-container">
          <h3>User Retention</h3>
          {cohortData?.retention && (
            <div className="retention-metrics">
              <p>Total Users: {cohortData.retention.length}</p>
              <p>
                Avg Events/User:{" "}
                {(
                  cohortData.retention.reduce((sum, u) => sum + u.total_events, 0) /
                  Math.max(cohortData.retention.length, 1)
                ).toFixed(1)}
              </p>
            </div>
          )}
        </div>

        <div className="chart-container">
          <h3>Live Event Stream</h3>
          <ul className="live-feed">
            {liveEvents.map((e, i) => (
              <li key={i}>
                <span className="tag">{e.event_type}</span> {e.user_id} — {e.value}
              </li>
            ))}
            {liveEvents.length === 0 && <li className="empty">Waiting for events…</li>}
          </ul>
        </div>
      </div>
    </div>
  );
};

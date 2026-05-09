import React from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, Pause, Play, ShieldCheck } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import "./styles.css";

const API_URL = "http://localhost:8000";
const WS_URL = "ws://localhost:8000";

function useStream(channel, initialValue) {
  const [data, setData] = React.useState(initialValue);
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    const socket = new WebSocket(`${WS_URL}/ws/${channel}`);
    socket.onopen = () => {
      setConnected(true);
      socket.send("subscribe");
    };
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data);
      setData((current) => {
        if (Array.isArray(current)) return [payload, ...current].slice(0, 80);
        return payload;
      });
    };
    socket.onclose = () => setConnected(false);
    return () => socket.close();
  }, [channel]);

  return [data, connected];
}

function App() {
  const [orderbook] = useStream("orderbook", { bids: [], asks: [], mid_price: 100, symbol: "TGD-USD" });
  const [trades] = useStream("trades", []);
  const [alerts] = useStream("alerts", []);
  const [metrics] = useStream("metrics", { total_orders: 0, total_cancels: 0, total_trades: 0, traders: [] });
  const [running, setRunning] = React.useState(false);

  React.useEffect(() => {
    fetch(`${API_URL}/health`).then((res) => res.json()).then((body) => setRunning(body.running));
  }, []);

  const toggleSimulation = async () => {
    const action = running ? "stop" : "start";
    const response = await fetch(`${API_URL}/simulation/${action}`, { method: "POST" });
    const body = await response.json();
    setRunning(body.running);
  };

  const chartData = React.useMemo(() => trades.slice(0, 40).reverse().map((trade, index) => ({
    index,
    price: trade.price,
    quantity: trade.quantity,
  })), [trades]);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="brand"><ShieldCheck size={24} /> TradeGuard</div>
          <p>Real-time market manipulation surveillance</p>
        </div>
        <div className="toolbar">
          <Metric label="Orders" value={metrics.total_orders} />
          <Metric label="Trades" value={metrics.total_trades} />
          <Metric label="Cancels" value={metrics.total_cancels} />
          <button className={running ? "danger" : "primary"} onClick={toggleSimulation}>
            {running ? <Pause size={18} /> : <Play size={18} />}
            {running ? "Stop" : "Start"}
          </button>
        </div>
      </header>

      <section className="grid">
        <Panel title="Order Book" icon={<Activity size={18} />}>
          <div className="book">
            <BookSide title="Bids" levels={orderbook.bids} side="bid" />
            <div className="mid">
              <span>{orderbook.symbol}</span>
              <strong>{Number(orderbook.mid_price).toFixed(2)}</strong>
            </div>
            <BookSide title="Asks" levels={orderbook.asks} side="ask" />
          </div>
        </Panel>

        <Panel title="Price Flow" icon={<Activity size={18} />} className="wide">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData}>
              <XAxis dataKey="index" tick={false} />
              <YAxis domain={["dataMin - 0.1", "dataMax + 0.1"]} width={46} />
              <Tooltip />
              <Line type="monotone" dataKey="price" stroke="#2f80ed" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Alerts" icon={<AlertTriangle size={18} />} className="alerts">
          {alerts.length === 0 ? <Empty text="No alerts yet" /> : alerts.map((alert) => <AlertRow key={alert.alert_id} alert={alert} />)}
        </Panel>

        <Panel title="Trade Feed">
          <div className="table">
            {trades.slice(0, 18).map((trade) => (
              <div className="row" key={trade.trade_id}>
                <span>{trade.buyer_id}</span>
                <strong>{Number(trade.price).toFixed(2)}</strong>
                <span>{trade.quantity}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Trader Risk">
          <div className="table">
            {metrics.traders?.map((trader) => (
              <div className="row" key={trader.trader_id}>
                <span>{trader.trader_id}</span>
                <strong>{Math.round(trader.cancel_ratio * 100)}%</strong>
                <span>{trader.cancels}/{trader.orders}</span>
              </div>
            ))}
          </div>
        </Panel>
      </section>
    </main>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Panel({ title, icon, className = "", children }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-title">{icon}{title}</div>
      {children}
    </section>
  );
}

function BookSide({ title, levels, side }) {
  return (
    <div>
      <div className="book-title">{title}</div>
      {levels.slice(0, 10).map((level) => (
        <div className={`level ${side}`} key={`${side}-${level.price}`}>
          <span>{Number(level.price).toFixed(2)}</span>
          <strong>{level.quantity}</strong>
          <small>{level.orders}</small>
        </div>
      ))}
    </div>
  );
}

function AlertRow({ alert }) {
  return (
    <article className={`alert ${alert.severity.toLowerCase()}`}>
      <div>
        <strong>{alert.alert_type.replaceAll("_", " ")}</strong>
        <span>{alert.trader_id}</span>
      </div>
      <p>{alert.reason}</p>
      <b>{Math.round(alert.score)}</b>
    </article>
  );
}

function Empty({ text }) {
  return <div className="empty">{text}</div>;
}

createRoot(document.getElementById("root")).render(<App />);

import { useEffect, useMemo, useState } from "react";

import logoUrl from "../openhealth_logo.avif";

const RUN_ID = import.meta.env.VITE_RUN_ID || "local-medmnist-001";
const APP_VERSION = "v0.3.2-react-vite";
const POLL_MS = 2500;
const TABS = ["metrics", "events", "clients", "configuration", "evidence"];

async function getJson(path) {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return response.json();
}

async function postJson(path) {
  const response = await fetch(`/api${path}`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return response.json();
}

function formatMetric(rows, key) {
  const values = rows
    .map((row) => row[key])
    .filter((value) => value !== "" && value !== undefined && value !== null);

  if (!values.length) {
    return "-";
  }

  const numeric = Number(values[values.length - 1]);
  return Number.isFinite(numeric) ? numeric.toFixed(4) : values[values.length - 1];
}

function latestRound(rows) {
  const rounds = rows
    .map((row) => Number(row.round))
    .filter((round) => Number.isFinite(round));

  return rounds.length ? Math.max(...rounds) : 0;
}

function Overview({ status, config, metrics, lastRefresh }) {
  const totalRounds = Number(config.rounds || config.flower_rounds || 0);
  const currentRound = latestRound(metrics);
  const localEpochs = config.local_epochs || config.training?.local_epochs || "-";

  const cards = [
    ["Run ID", status.run_id || RUN_ID],
    ["Status", status.status || "-"],
    ["Dataset", config.dataset_subset || "-"],
    [
      "Registered clients",
      `${status.registered_client_count ?? "-"} / ${status.min_clients ?? "-"}`,
    ],
    ["Rounds", totalRounds || "-"],
    ["Local epochs", localEpochs],
    ["Progress", totalRounds ? `${currentRound} / ${totalRounds}` : "-"],
    ["Last poll", lastRefresh || "-"],
    ["Latest loss", formatMetric(metrics, "loss")],
    ["Latest accuracy", formatMetric(metrics, "accuracy")],
    ["Train loss", formatMetric(metrics, "train_loss")],
    ["Train accuracy", formatMetric(metrics, "train_accuracy")],
  ];

  return (
    <section className="panel">
      <h3>Overview</h3>
      <div className="cards">
        {cards.map(([label, value]) => (
          <div className="card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>

      <div className="scope">
        This MVP demonstrates FL infrastructure and evidence capture. Governance is
        pass-through. FCaC-style admission control is not implemented.
      </div>
    </section>
  );
}

function MetricsTable({ rows }) {
  if (!rows.length) {
    return <table><tbody><tr><td>No metrics available yet.</td></tr></tbody></table>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Round</th>
          <th>Fit clients</th>
          <th>Eval clients</th>
          <th>Loss</th>
          <th>Accuracy</th>
          <th>Train loss</th>
          <th>Train accuracy</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.round || "round"}-${index}`}>
            <td>{row.round || "-"}</td>
            <td>{row.fit_client_count || "-"}</td>
            <td>{row.eval_client_count || "-"}</td>
            <td>{row.loss || "-"}</td>
            <td>{row.accuracy || "-"}</td>
            <td>{row.train_loss || "-"}</td>
            <td>{row.train_accuracy || "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EventsTimeline({ events }) {
  if (!events.length) {
    return <p className="muted">No events available yet.</p>;
  }

  return (
    <div>
      {[...events].reverse().map((event, index) => (
        <details key={`${event.timestamp || "event"}-${index}`}>
          <summary>
            {event.event_type || "event"} - {event.component || "component"} -{" "}
            {event.timestamp || ""}
          </summary>
          <pre>{JSON.stringify(event, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function ClientsTable({ participants }) {
  if (!participants.length) {
    return <table><tbody><tr><td>No clients available.</td></tr></tbody></table>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Organisation</th>
          <th>Label</th>
          <th>Partition</th>
          <th>Enabled</th>
        </tr>
      </thead>
      <tbody>
        {participants.map((client) => (
          <tr key={client.org_id}>
            <td>{client.org_id}</td>
            <td>{client.label || "-"}</td>
            <td>{client.partition ?? "-"}</td>
            <td>{String(client.enabled)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EvidenceArtifacts() {
  const artefacts = [
    "experiment_config.json",
    "participants.json",
    "dataset_split_summary.csv",
    "metrics.csv",
    "events.jsonl",
    "final_model_metadata.json",
    "README_reproduce_this_run.md",
  ];

  return (
    <>
      <p>
        Expected artefacts under <code>runs/{RUN_ID}/</code>:
      </p>
      <ul>
        {artefacts.map((artefact) => (
          <li key={artefact}>{artefact}</li>
        ))}
      </ul>
    </>
  );
}

function TabPanel({ activeTab, metrics, events, participants, config }) {
  return (
    <>
      <section className={`panel ${activeTab === "metrics" ? "" : "hidden"}`}>
        <h3>Metrics</h3>
        <MetricsTable rows={metrics} />
      </section>

      <section className={`panel ${activeTab === "events" ? "" : "hidden"}`}>
        <h3>Event timeline</h3>
        <EventsTimeline events={events} />
      </section>

      <section className={`panel ${activeTab === "clients" ? "" : "hidden"}`}>
        <h3>Clients</h3>
        <ClientsTable participants={participants} />
      </section>

      <section className={`panel ${activeTab === "configuration" ? "" : "hidden"}`}>
        <h3>Configuration</h3>
        <pre>{JSON.stringify(config, null, 2)}</pre>
      </section>

      <section className={`panel ${activeTab === "evidence" ? "" : "hidden"}`}>
        <h3>Evidence artefacts</h3>
        <EvidenceArtifacts />
      </section>
    </>
  );
}

function Header() {
  return (
    <header>
      <div className="brand">
        <img className="logo-img" src={logoUrl} alt="OpenHealth logo" />
        <div>
          <h1>OpenHealth</h1>
          <div className="muted">VFP Federated Computing MVP</div>
        </div>
      </div>
      <div className="badges">
        <span className="badge blue">vfp-core</span>
        <span className="badge orange">vfp-governance: pass-through</span>
        <span className="badge gray">FCaC not enabled</span>
        <span className="badge green">{APP_VERSION}</span>
      </div>
    </header>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("metrics");
  const [status, setStatus] = useState({});
  const [experiment, setExperiment] = useState({});
  const [metrics, setMetrics] = useState([]);
  const [events, setEvents] = useState([]);
  const [lastRefresh, setLastRefresh] = useState("");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const config = experiment.experiment_config || {};
  const participants = useMemo(
    () => experiment.participants?.participants || [],
    [experiment.participants]
  );

  async function refreshAll() {
    try {
      const [statusPayload, experimentPayload, metricsPayload, eventsPayload] =
        await Promise.all([
          getJson(`/experiments/${RUN_ID}/status`),
          getJson(`/experiments/${RUN_ID}`),
          getJson(`/experiments/${RUN_ID}/metrics`),
          getJson(`/experiments/${RUN_ID}/events?limit=150`),
        ]);

      setStatus(statusPayload);
      setExperiment(experimentPayload);
      setMetrics(metricsPayload.metrics || []);
      setEvents(eventsPayload.events || []);
      setLastRefresh(new Date().toLocaleTimeString());
      setError("");
    } catch (err) {
      setStatus((current) => ({ ...current, status: "error" }));
      setError(err.message);
      console.error(err);
    }
  }

  async function startExperiment() {
    setStarting(true);
    try {
      await postJson(`/experiments/${RUN_ID}/start`);
      await refreshAll();
    } catch (err) {
      setError(err.message);
      console.error(err);
    } finally {
      setStarting(false);
    }
  }

  useEffect(() => {
    refreshAll();
    const intervalId = window.setInterval(refreshAll, POLL_MS);
    return () => window.clearInterval(intervalId);
  }, []);

  return (
    <>
      <Header />

      <main>
        <div className="top-row">
          <div>
            <h2>Experiment dashboard</h2>
            <div className="muted">Reproducible FL infrastructure scaffold</div>
          </div>
          <div>
            <button
              id="startButton"
              type="button"
              onClick={startExperiment}
              disabled={starting || !status.can_start}
            >
              START EXPERIMENT
            </button>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        <Overview
          status={status}
          config={config}
          metrics={metrics}
          lastRefresh={lastRefresh}
        />

        <div className="tabs">
          {TABS.map((tab) => (
            <button
              className={`tab ${activeTab === tab ? "active" : ""}`}
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
            >
              {tab === "clients" ? "Clients" : tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>

        <TabPanel
          activeTab={activeTab}
          metrics={metrics}
          events={events}
          participants={participants}
          config={config}
        />
      </main>
    </>
  );
}

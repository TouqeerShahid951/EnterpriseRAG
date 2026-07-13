import { Activity, Loader2 } from "lucide-react";

import { QueryTrackerControls } from "./query-tracker/QueryTrackerControls";
import { QueryTrackerResults } from "./query-tracker/QueryTrackerResults";
import {
  useQueryTrackerController,
  type QueryTrackerController,
  type QueryTrackerControllerInput,
} from "./query-tracker/useQueryTrackerController";

export function QueryTrackerPanel(props: QueryTrackerPanelProps) {
  const controller = useQueryTrackerController(props);
  return <QueryTrackerPanelView controller={controller} />;
}

function QueryTrackerPanelView({ controller }: { controller: QueryTrackerController }) {
  const { controls, results } = controller;

  return (
    <div className="rag-eval-screen rag-eval-tracker-screen">
      <section className="sv-panel rag-eval-tracker-console">
        <div className="rag-eval-section-header">
          <div>
            <h2 className="sv-section-title">Query Tracker</h2>
            <p>Run one live query and inspect the graph, evidence, answer, and timings.</p>
          </div>
          <span className={controls.isRunning ? "rag-eval-tracker-live active" : "rag-eval-tracker-live"}>
            {controls.isRunning ? <Loader2 className="animate-spin" size={14} /> : <Activity size={14} />}
            {controls.isRunning ? "Streaming" : "Ready"}
          </span>
        </div>
        <QueryTrackerControls model={controls} />
      </section>

      <QueryTrackerResults model={results} />
    </div>
  );
}

type QueryTrackerPanelProps = QueryTrackerControllerInput;

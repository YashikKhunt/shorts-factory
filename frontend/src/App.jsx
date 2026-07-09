import React from "react";
import DropZone from "./components/DropZone.jsx";
import JobCard from "./components/JobCard.jsx";
import { usePolling, uploadFiles } from "./api.js";

export default function App() {
  const { jobs, warnings } = usePolling();
  const active = jobs.filter((j) => j.status === "queued" || j.status === "running").length;

  return (
    <div className="shell">
      <header className="masthead">
        <h1>
          Shorts<em>/</em>Factory
        </h1>
        <span className="tag">raw clip in — ready short out</span>
      </header>

      {warnings.length > 0 && (
        <div className="warnings">
          {warnings.map((w, i) => (
            <div key={i}>⚠ {w}</div>
          ))}
        </div>
      )}

      <DropZone onFiles={uploadFiles} />

      <div className="queue-head">
        <h2>
          Render queue — <span className="count">{active} active</span> /{" "}
          {jobs.length} total
        </h2>
      </div>

      {jobs.length === 0 ? (
        <div className="empty">Nothing in the queue. Drop trip footage above.</div>
      ) : (
        jobs.map((job) => <JobCard key={job.id} job={job} />)
      )}
    </div>
  );
}

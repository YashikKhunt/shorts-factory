import React from "react";
import ResultPanel from "./ResultPanel.jsx";
import { deleteJob } from "../api.js";

const STAGE_LABELS = {
  queued: "waiting in queue",
  probing: "reading video info",
  selecting: "finding best segment",
  transcribing: "listening for speech",
  analyzing_clips: "analyzing each clip",
  deciding_edit: "AI planning the edit",
  analyzing: "AI writing titles",
  rendering: "rendering",
  writing_outputs: "saving files",
  done: "ready to post",
  error: "failed",
};

export default function JobCard({ job }) {
  const label = STAGE_LABELS[job.stage] || job.stage;

  return (
    <article className={`card ${job.status}`}>
      {job.status === "done" ? (
        <img className="thumb" src={`/api/jobs/${job.id}/thumbnail`} alt="" />
      ) : (
        <div className="thumb ph">{job.status === "error" ? "✕" : "processing…"}</div>
      )}

      <div className="card-body">
        <div className="card-top">
          <div className="fname">{job.filename}</div>
          <span className={`badge ${job.status}`}>
            {job.status === "running" ? label : job.status}
          </span>
        </div>

        {(job.status === "running" || job.status === "queued") && (
          <>
            <div className="bar">
              <div
                style={{
                  width:
                    job.stage === "rendering" ? `${job.progress}%` : "4%",
                }}
              />
            </div>
            <div className="stage-line">
              {label}
              {job.stage === "rendering" && ` — ${job.progress.toFixed(0)}%`}
            </div>
          </>
        )}

        {job.status === "error" && (
          <>
            <div className="err-line">{job.error}</div>
            <div className="actions">
              <button className="btn ghost" onClick={() => deleteJob(job.id)}>
                Remove
              </button>
            </div>
          </>
        )}

        {job.status === "done" && job.result && <ResultPanel job={job} />}
      </div>
    </article>
  );
}

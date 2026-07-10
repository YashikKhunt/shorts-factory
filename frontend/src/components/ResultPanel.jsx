import React, { useState } from "react";
import { deleteJob, revealJob } from "../api.js";

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className={`copy ${copied ? "copied" : ""}`}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      }}
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

export default function ResultPanel({ job }) {
  const r = job.result;
  return (
    <div className="result">
      <video
        className="preview"
        src={`/api/jobs/${job.id}/video`}
        controls
        muted
        playsInline
        preload="metadata"
      />
      <div className="meta">
        <h4>Titles — pick one</h4>
        {r.titles.map((t, i) => (
          <div className="title-row" key={i}>
            <span>{t}</span>
            <CopyButton text={t} />
          </div>
        ))}

        <h4>
          Hashtags <CopyButton text={r.hashtags.join(" ")} />
        </h4>
        <div className="hashtags-row">{r.hashtags.join(" ")}</div>

        <h4>On-video hook</h4>
        <span className="hook-chip">{r.hook}</span>
        {r.clips && (
          <div className="stage-line" style={{ marginTop: 10 }}>
            ✂ cut from {r.clips.length} clips
            {r.edit_fallback && " (energy-based fallback edit — set ANTHROPIC_API_KEY for AI cuts)"}
          </div>
        )}
        {r.metadata_fallback && (
          <div className="stage-line" style={{ marginTop: 10 }}>
            ⚠ offline fallback titles — set ANTHROPIC_API_KEY in .env for AI ones
          </div>
        )}

        <div className="actions">
          <a className="btn primary" href={`/api/jobs/${job.id}/download`}>
            Download
          </a>
          <button className="btn" onClick={() => revealJob(job.id)}>
            Reveal in Finder
          </button>
          <button className="btn ghost" onClick={() => deleteJob(job.id)}>
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}

import React, { useRef, useState } from "react";

export default function DropZone({ onFiles }) {
  const input = useRef(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState(null);
  const [combine, setCombine] = useState(true);

  const handle = async (fileList) => {
    const files = [...fileList].filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|avi|mkv|webm)$/i.test(f.name));
    if (!files.length) return;
    setError(null);
    try {
      await onFiles(files, combine && files.length > 1);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div
      className={`dropzone ${drag ? "drag" : ""}`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        handle(e.dataTransfer.files);
      }}
    >
      <div className="big">{drag ? "Release to queue" : "Drop trip videos here"}</div>
      <div className="sub">
        or click to browse — multiple files OK · trims to ~25s · 9:16 · music ·
        captions · AI titles
      </div>
      <label
        className="combine-row"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          type="checkbox"
          checked={combine}
          onChange={(e) => setCombine(e.target.checked)}
        />
        Combine multiple clips into one Short (AI picks the cuts)
      </label>
      {error && <div className="err-line">{error}</div>}
      <input
        ref={input}
        type="file"
        accept="video/*"
        multiple
        hidden
        onChange={(e) => {
          handle(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

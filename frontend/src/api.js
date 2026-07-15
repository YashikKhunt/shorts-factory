import { useEffect, useRef, useState } from "react";

export async function uploadFiles(files, combine = false) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  form.append("combine", combine ? "1" : "0");
  const res = await fetch("/api/upload", { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json()).detail || "Upload failed");
  return res.json();
}

export function usePolling(intervalMs = 1500) {
  const [data, setData] = useState({ jobs: [], warnings: [] });
  const busy = useRef(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (busy.current) return;
      busy.current = true;
      try {
        const res = await fetch("/api/jobs");
        if (res.ok && alive) setData(await res.json());
      } catch {
        /* server restarting — keep polling */
      } finally {
        busy.current = false;
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return data;
}

export const deleteJob = (id) => fetch(`/api/jobs/${id}`, { method: "DELETE" });
export const revealJob = (id) => fetch(`/api/jobs/${id}/reveal`, { method: "POST" });

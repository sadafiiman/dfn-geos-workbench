/* Live log auto-refresh + cancel buttons */
(function () {
  "use strict";

  const logbox = document.getElementById("logbox");
  if (logbox) {
    const jobId = logbox.dataset.job;
    const done = logbox.dataset.done === "1";
    if (!done) {
      let lastLen = 0;
      const tick = async () => {
        try {
          const r = await fetch(`/api/job?id=${jobId}`, {cache: "no-store"});
          const data = await r.json();
          if (data.log && data.log.length !== lastLen) {
            lastLen = data.log.length;
            logbox.textContent = data.log;
            logbox.scrollTop = logbox.scrollHeight;
          }
          if (data.job.status !== "running" && data.job.status !== "queued") {
            setTimeout(() => location.reload(), 800);
            return;
          }
        } catch (e) { /* keep polling */ }
        setTimeout(tick, 1500);
      };
      tick();
    }
  }

  // ⧉ Copy buttons: copy the text of the element named in data-copy-target.
  // Uses the async clipboard API when available, with a textarea fallback
  // for plain-http (non-secure) contexts.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button.copy-btn");
    if (!btn) return;
    const el = document.querySelector(btn.dataset.copyTarget);
    if (!el) return;
    const text = el.textContent || "";
    const flash = (ok) => {
      const old = btn.textContent;
      btn.textContent = ok ? "Copied ✓" : "Copy failed";
      setTimeout(() => { btn.textContent = old; }, 1200);
    };
    const fallbackCopy = () => {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      flash(ok);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => flash(true), fallbackCopy);
    } else {
      fallbackCopy();
    }
  });

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-cancel]");
    if (btn && confirm("Cancel this job?")) {
      fetch(`/job/${btn.dataset.cancel}/cancel`, {method: "POST"})
        .then(() => location.reload());
    }
  });

  // Auto-refresh case/dashboard pages while any job is queued or running,
  // so an upload-and-process flow shows results without manual reloads.
  if (!logbox) {
    const busy = document.querySelector(".badge-running, .badge-queued");
    if (busy) {
      setTimeout(() => location.reload(), 4000);
    }
  }
})();

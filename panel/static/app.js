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

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-cancel]");
    if (btn && confirm("Cancel this job?")) {
      fetch(`/job/${btn.dataset.cancel}/cancel`, {method: "POST"})
        .then(() => location.reload());
    }
  });
})();

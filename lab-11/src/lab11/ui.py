"""The review UI: one static HTML page.

Lists jobs via ``GET /v1/briefs`` and offers approve/reject buttons on
completed jobs, plus a small form to submit a new brief. All calls go through
``fetch()`` with the bearer token.

Caveat, stated honestly: the token is embedded in the served page so the demo
works out of the box. In front of real users this page would sit behind the
operator's own login, not a shared secret in the markup.
"""
from __future__ import annotations

REVIEW_UI = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Lab 11 — brief review</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 14px; }
.status-completed { color: green; } .status-failed { color: red; }
.status-running { color: orange; } .status-queued { color: gray; }
button { margin-right: 4px; }
form { margin-bottom: 1.5em; }
input[type=text] { width: 420px; }
</style>
</head>
<body>
<h1>Brief jobs</h1>
<form id="new">
  <input type="text" id="question" placeholder="Question for the brief pipeline" required>
  <input type="text" id="idem" placeholder="Idempotency-Key (optional)">
  <button type="submit">Submit brief</button>
</form>
<table>
<thead><tr><th>job</th><th>question</th><th>status</th><th>tokens</th><th>decision</th><th>actions</th></tr></thead>
<tbody id="rows"></tbody>
</table>
<script>
const TOKEN = "__TOKEN__";
const H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"};

async function refresh() {
  const r = await fetch("/v1/briefs", {headers: H});
  const data = await r.json();
  const rows = document.getElementById("rows");
  rows.innerHTML = "";
  for (const j of data.jobs) {
    const tr = document.createElement("tr");
    const actions = j.status === "completed" && !j.decision
      ? '<button data-act="approve" data-id="' + j.job_id + '">approve</button>'
        + '<button data-act="reject" data-id="' + j.job_id + '">reject</button>'
      : (j.error ? j.error : "");
    tr.innerHTML = "<td><code>" + j.job_id.slice(0, 8) + "</code></td>"
      + "<td>" + j.question + "</td>"
      + '<td class="status-' + j.status + '">' + j.status + "</td>"
      + "<td>" + j.tokens_used + "</td>"
      + "<td>" + (j.decision || "") + "</td>"
      + "<td>" + actions + "</td>";
    rows.appendChild(tr);
  }
  rows.querySelectorAll("button").forEach(b => b.addEventListener("click", async () => {
    await fetch("/v1/briefs/" + b.dataset.id + "/" + b.dataset.act,
                {method: "POST", headers: H});
    refresh();
  }));
}

document.getElementById("new").addEventListener("submit", async (e) => {
  e.preventDefault();
  const headers = {...H};
  const idem = document.getElementById("idem").value;
  if (idem) headers["Idempotency-Key"] = idem;
  await fetch("/v1/briefs", {method: "POST", headers,
    body: JSON.stringify({question: document.getElementById("question").value})});
  document.getElementById("question").value = "";
  refresh();
});

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""

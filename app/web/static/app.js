const $ = (s) => document.querySelector(s);

async function runPipeline() {
  $("#status").textContent = "运行中…";
  try {
    const r = await fetch("/api/run", { method: "POST" });
    const d = await r.json();
    $("#status").textContent = "完成 run_id=" + d.run_id + " status=" + d.run.status;
    loadAll();
  } catch (e) {
    $("#status").textContent = "失败：" + e;
  }
}

async function loadRuns() {
  const runs = await (await fetch("/api/runs")).json();
  $("#runList").innerHTML = runs.map(r =>
    `<li data-id="${r.id}">#${r.id} ${r.status} ${r.started_at}</li>`).join("");
  document.querySelectorAll("#runList li").forEach(li => li.onclick = async () => {
    const d = await (await fetch("/api/runs/" + li.dataset.id)).json();
    $("#runDetail").textContent = d.log || d.summary_json || "";
  });
}

async function loadBureaus() {
  const bs = await (await fetch("/api/bureaus")).json();
  $("#bureauList").innerHTML = bs.map(b => `<li>${b.name} (${b.level})</li>`).join("");
}

async function queryData() {
  const p = new URLSearchParams();
  if ($("#fRegion").value) p.set("region", $("#fRegion").value);
  if ($("#fIndicator").value) p.set("indicator", $("#fIndicator").value);
  if ($("#fYear").value) p.set("year", $("#fYear").value);
  const rows = await (await fetch("/api/data?" + p)).json();
  const cols = rows.length ? Object.keys(rows[0]) : [];
  document.querySelector("#dataTable thead tr").innerHTML =
    cols.map(c => `<th>${c}</th>`).join("");
  $("#dataTable tbody").innerHTML = rows.map(r =>
    `<tr>${cols.map(c => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`).join("");
}

function loadAll() { loadRuns(); loadBureaus(); queryData(); }

$("#runBtn").onclick = runPipeline;
$("#queryBtn").onclick = queryData;
loadAll();

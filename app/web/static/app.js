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

async function loadFilters() {
  try {
    const f = await (await fetch("/api/filters")).json();
    const fill = (id, vals) => {
      const dl = $(id);
      dl.innerHTML = vals.map(v => `<option value="${v}">`).join("");
    };
    fill("#dlRegions", f.regions);
    fill("#dlIndicators", f.indicators);
    fill("#dlYears", f.years);
  } catch (e) { /* 候选提示失败不影响查询 */ }
}

async function renderRows(d, qs) {
  const rows = d.rows || [];
  const cols = rows.length ? Object.keys(rows[0]) : [];
  document.querySelector("#dataTable thead tr").innerHTML =
    cols.map(c => `<th>${c}</th>`).join("");
  $("#dataTable tbody").innerHTML = rows.map(r =>
    `<tr>${cols.map(c => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`).join("");
  const warns = d.warnings || [];
  const m = d.matched || {};
  let matchedNote = "";
  if (Object.keys(m).length && (m.regions?.length || m.indicator || m.year)) {
    const parts = [];
    if (m.regions?.length) parts.push("地区 " + m.regions.join("、"));
    if (m.indicator) parts.push("指标 " + m.indicator);
    if (m.year) parts.push("年份 " + m.year);
    if (parts.length) matchedNote = "已识别：" + parts.join(" · ") + " → ";
  }
  $("#queryMsg").textContent = matchedNote + (warns.length
    ? "提示：" + warns.join("；") : (rows.length ? "" : "（无匹配数据）"));
  $("#queryMsg").style.color = (warns.length || (!rows.length && matchedNote)) ? "#b36b00" : "#888";
  $("#exportBtn").href = "/api/export?" + qs;
}

async function queryText() {
  const v = $("#fText").value.trim();
  if (!v) { queryAdvanced(); return; }
  const p = new URLSearchParams({ text: v });
  const d = await (await fetch("/api/data?" + p)).json();
  await renderRows(d, p);
}

async function queryAdvanced() {
  const p = new URLSearchParams();
  if ($("#fRegion").value) p.set("region", $("#fRegion").value);
  if ($("#fIndicator").value) p.set("indicator", $("#fIndicator").value);
  if ($("#fYear").value) p.set("year", $("#fYear").value);
  const d = await (await fetch("/api/data?" + p)).json();
  await renderRows(d, p);
}

function loadAll() { loadRuns(); loadBureaus(); loadFilters(); queryText(); }

async function showAnalysis() {
  const r = await fetch("/api/analysis?format=html");
  $("#analysisFrame").srcdoc = await r.text();
}

$("#runBtn").onclick = runPipeline;
$("#queryBtn").onclick = queryText;
$("#queryAdvancedBtn").onclick = queryAdvanced;
$("#fText").addEventListener("keydown", e => { if (e.key === "Enter") queryText(); });
$("#fRegion").addEventListener("keydown", e => { if (e.key === "Enter") queryAdvanced(); });
$("#fIndicator").addEventListener("keydown", e => { if (e.key === "Enter") queryAdvanced(); });
$("#fYear").addEventListener("keydown", e => { if (e.key === "Enter") queryAdvanced(); });
$("#analysisBtn").onclick = showAnalysis;
loadAll();

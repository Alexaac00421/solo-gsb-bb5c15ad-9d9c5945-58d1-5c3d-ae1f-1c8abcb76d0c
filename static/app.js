"use strict";

const $ = (id) => document.getElementById(id);
let state = null;
let currentBatch = 0;

async function api(path, options) {
  const resp = await fetch(path, options);
  let body = null;
  try { body = await resp.json(); } catch (e) { /* 非 JSON 响应 */ }
  if (!resp.ok) {
    throw new Error((body && body.error) || `请求失败（HTTP ${resp.status}）`);
  }
  return body;
}

function showMessage(text, isError) {
  const el = $("message");
  el.textContent = text;
  el.className = "message " + (isError ? "error" : "ok");
}

async function refresh() {
  state = await api("/api/state");
  render();
}

function fillSettingsForm(s) {
  const form = $("settings-form");
  for (const key of ["bed_w", "bed_h", "margin_left", "margin_right",
                     "margin_bottom", "margin_top", "spacing"]) {
    form.elements[key].value = s ? s[key] : "";
  }
}

function render() {
  const model = state.model;
  $("model-info").textContent = model
    ? `当前模型：${model.filename}，份数 ${model.copies}，` +
      `XY 投影占位 ${model.width.toFixed(2)} × ${model.height.toFixed(2)} mm，` +
      `${model.triangles} 个三角形。上传新文件将替换并令旧排布失效。`
    : "尚未上传模型。";

  const layout = state.layout;
  const section = $("result-section");
  if (!layout) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const stale = layout.status !== "valid";
  $("stale-banner").hidden = !stale;
  $("export-btn").disabled = stale;

  const result = layout.result;
  $("batch-summary").textContent =
    `共 ${result.batch_count} 批` +
    (result.proven_optimal ? "（已证明为最小批次数）" : "（求解限时内未证明最优）") +
    (stale ? " —— 已失效" : "");

  const tabs = $("batch-tabs");
  tabs.innerHTML = "";
  result.batches.forEach((batch, i) => {
    const btn = document.createElement("button");
    btn.textContent = `第 ${batch.batch} 批（${batch.instances.length} 件）`;
    btn.className = i === currentBatch ? "active" : "";
    btn.onclick = () => { currentBatch = i; render(); };
    tabs.appendChild(btn);
  });
  if (currentBatch >= result.batches.length) currentBatch = 0;

  drawBatch(result.batches[currentBatch], result.bed);
  fillTable(result.batches[currentBatch]);
}

function drawBatch(batch, bed) {
  const canvas = $("canvas");
  const ctx = canvas.getContext("2d");
  const pad = 24;
  const scale = Math.min((canvas.width - 2 * pad) / bed.width,
                         (canvas.height - 2 * pad) / bed.height);
  const ox = pad, oy = pad;
  const X = (mm) => ox + mm * scale;
  const Y = (mm) => canvas.height - oy - mm * scale; // Y 轴翻转

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // 床体与留白
  ctx.fillStyle = "#e8eaed";
  ctx.fillRect(X(0), Y(bed.height), bed.width * scale, bed.height * scale);
  const m = bed.margins;
  const pw = bed.width - m.left - m.right;
  const ph = bed.height - m.bottom - m.top;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(X(m.left), Y(m.bottom + ph), pw * scale, ph * scale);
  ctx.strokeStyle = "#1f2328";
  ctx.strokeRect(X(0), Y(bed.height), bed.width * scale, bed.height * scale);
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#8c959f";
  ctx.strokeRect(X(m.left), Y(m.bottom + ph), pw * scale, ph * scale);
  ctx.setLineDash([]);

  // 实例
  const colors = ["#1f6feb", "#8250df", "#cf222e", "#1a7f37", "#bf3989",
                  "#9a6700", "#0969da", "#6e7781", "#d4a72c", "#0550ae",
                  "#953800", "#116329"];
  batch.instances.forEach((inst, i) => {
    const color = colors[i % colors.length];
    // 间距光晕（每侧 spacing/2，用于直观展示分隔）
    if (bed.spacing > 0) {
      const half = bed.spacing / 2;
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.5;
      ctx.strokeRect(X(inst.x - half), Y(inst.y + inst.height + half),
                     (inst.width + bed.spacing) * scale,
                     (inst.height + bed.spacing) * scale);
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
    }
    ctx.fillStyle = color + "33";
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.fillRect(X(inst.x), Y(inst.y + inst.height),
                 inst.width * scale, inst.height * scale);
    ctx.strokeRect(X(inst.x), Y(inst.y + inst.height),
                   inst.width * scale, inst.height * scale);
    ctx.fillStyle = "#1f2328";
    ctx.font = "12px sans-serif";
    ctx.fillText(`#${inst.copy}${inst.rotation === 90 ? " 90°" : ""}`,
                 X(inst.x) + 4, Y(inst.y + inst.height) + 14);
  });
  ctx.lineWidth = 1;
}

function fillTable(batch) {
  const tbody = $("instance-table").querySelector("tbody");
  tbody.innerHTML = "";
  for (const inst of batch.instances) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${inst.model}</td><td>${inst.copy}</td>` +
      `<td>${inst.rotation}°</td><td>${inst.x.toFixed(2)}</td>` +
      `<td>${inst.y.toFixed(2)}</td>` +
      `<td>${inst.width.toFixed(2)} × ${inst.height.toFixed(2)}</td>`;
    tbody.appendChild(tr);
  }
}

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const payload = {};
  for (const key of ["bed_w", "bed_h", "margin_left", "margin_right",
                     "margin_bottom", "margin_top", "spacing"]) {
    payload[key] = form.elements[key].value;
  }
  try {
    state = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showMessage("设置已保存。", false);
    render();
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("model-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const fd = new FormData();
  fd.append("file", form.elements.file.files[0]);
  fd.append("copies", form.elements.copies.value);
  try {
    state = await api("/api/model", { method: "POST", body: fd });
    showMessage("模型已上传。", false);
    render();
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("solve-btn").addEventListener("click", async () => {
  showMessage("求解中…", false);
  try {
    state = await api("/api/solve", { method: "POST" });
    currentBatch = 0;
    showMessage("求解完成。", false);
    render();
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("export-btn").addEventListener("click", async () => {
  try {
    const resp = await fetch("/api/export");
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new Error((body && body.error) || `导出失败（HTTP ${resp.status}）`);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "layout.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showMessage(err.message, true);
  }
});

(async () => {
  await refresh();
  fillSettingsForm(state.settings);
})();

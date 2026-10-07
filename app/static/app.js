"use strict";

let state = null;

const PALETTE = [
  "#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa",
  "#f472b6", "#22d3ee", "#a3e635", "#fb923c", "#94a3b8",
  "#e879f9", "#4ade80",
];
function colorFor(modelId) {
  const ids = (state?.models ?? []).map(m => m.id);
  const i = ids.indexOf(modelId);
  return PALETTE[(i >= 0 ? i : modelId) % PALETTE.length];
}

async function api(path, options) {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) { /* ignore */ }
  if (!res.ok) {
    throw new Error(data?.error || `请求失败（HTTP ${res.status}）`);
  }
  return data;
}

function toast(msg, ms = 4000) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function fmt(v) { return (Math.round(v * 100) / 100).toString(); }

function render() {
  if (!state) return;
  const c = state.config;
  document.getElementById("bed_width_mm").value = c.bed_width_mm;
  document.getElementById("bed_depth_mm").value = c.bed_depth_mm;
  document.getElementById("margin_mm").value = c.margin_mm;
  document.getElementById("gap_mm").value = c.gap_mm;

  const pw = state.printable.width_mm, pd = state.printable.depth_mm;
  document.getElementById("printable-info").textContent =
    `留白内可用区域：${fmt(pw)} × ${fmt(pd)} mm（坐标原点为打印床左下角，可用区域原点 (${fmt(c.margin_mm)}, ${fmt(c.margin_mm)})）`;

  // 模型表
  const tbody = document.querySelector("#models-table tbody");
  tbody.innerHTML = "";
  for (const m of state.models) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${escapeHtml(m.name)}</td>` +
      `<td>${fmt(m.width_mm)} × ${fmt(m.depth_mm)} × ${fmt(m.height_mm)}</td>` +
      `<td>${m.triangles}</td>` +
      `<td><input type="number" min="1" max="12" value="${m.copies}" data-id="${m.id}" class="copies-input"></td>` +
      `<td><button class="link-btn" data-del="${m.id}">删除</button></td>`;
    tbody.appendChild(tr);
  }
  document.getElementById("instances-info").textContent =
    `实例总数：${state.total_instances} / ${state.max_total_instances}`;

  document.querySelectorAll(".copies-input").forEach(inp => {
    inp.addEventListener("change", async () => {
      try {
        state = await api(`/api/models/${inp.dataset.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ copies: Number(inp.value) }),
        });
        render();
      } catch (e) { toast(e.message); state = await refresh(); }
    });
  });
  document.querySelectorAll("[data-del]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("删除该模型？")) return;
      state = await api(`/api/models/${btn.dataset.del}`, { method: "DELETE" });
      render();
    });
  });

  renderSolution();
}

function refresh() {
  return api("/api/state");
}

function renderSolution() {
  const sol = state.solution;
  const banner = document.getElementById("status-banner");
  const results = document.getElementById("results");
  const exportBtn = document.getElementById("export-btn");
  results.innerHTML = "";
  banner.classList.add("hidden");

  if (!sol) {
    showBanner("warn", "尚无排布结果：设置参数并上传模型后点击“重新求解”。");
    exportBtn.disabled = true;
    return;
  }
  if (!sol.valid) {
    showBanner("err", "当前排布已失效：床参数或模型已发生变更。请重新求解，求解前无法导出 JSON。");
    exportBtn.disabled = true;
    renderBatches(sol, { dimmed: true });
    return;
  }
  showBanner("ok", `求解完成：共 ${sol.total_instances} 个实例，最少需要 ${sol.batch_count} 批。`);
  exportBtn.disabled = false;
  renderBatches(sol, { dimmed: false });
}

function showBanner(kind, text) {
  const banner = document.getElementById("status-banner");
  banner.className = `banner ${kind}`;
  banner.textContent = text;
}

function renderBatches(sol, { dimmed }) {
  const results = document.getElementById("results");
  const c = sol.config_snapshot;
  for (const b of sol.batches) {
    const wrap = document.createElement("div");
    wrap.className = "batch";
    wrap.style.opacity = dimmed ? "0.55" : "1";
    const title = document.createElement("h3");
    title.textContent = `第 ${b.batch} / ${sol.batch_count} 批（${b.placements.length} 件）`;
    wrap.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "batch-grid";

    const cv = document.createElement("canvas");
    drawBed(cv, c, b.placements);
    grid.appendChild(cv);
    grid.appendChild(buildTable(b));
    wrap.appendChild(grid);
    results.appendChild(wrap);
  }
}

function buildTable(batch) {
  const table = document.createElement("table");
  table.style.width = "auto";
  table.innerHTML =
    "<thead><tr><th>模型</th><th>份号</th><th>方向</th><th>左下角 (x, y) mm</th><th>占位 宽×深 mm</th></tr></thead>";
  const tbody = document.createElement("tbody");
  for (const p of batch.placements) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${escapeHtml(p.name)}</td>` +
      `<td>${p.index}</td>` +
      `<td>${p.rotation}°</td>` +
      `<td>${fmt(p.x_mm)}, ${fmt(p.y_mm)}</td>` +
      `<td>${fmt(p.width_mm)} × ${fmt(p.depth_mm)}</td>`;
    tr.style.background = colorFor(p.model_id) + "55";
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}

function drawBed(canvas, conf, placements) {
  const W = conf.bed_width_mm, D = conf.bed_depth_mm, m = conf.margin_mm;
  const maxPx = 380;
  const s = Math.min(maxPx / W, maxPx / D);
  const pad = 24; // 坐标轴留白
  canvas.width = W * s + pad * 2;
  canvas.height = D * s + pad * 2;
  const ctx = canvas.getContext("2d");

  // 画布 y 向下；把床左下角放到画布 (pad, H-pad)
  const X = mm => pad + mm * s;
  const Y = mm => canvas.height - pad - mm * s;

  // 打印床外框
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(X(0), Y(D), W * s, D * s);
  ctx.strokeStyle = "#334155";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(X(0), Y(D), W * s, D * s);

  // 留白区域
  ctx.strokeStyle = "#dc2626";
  ctx.setLineDash([6, 4]);
  ctx.lineWidth = 1;
  const pw = W - 2 * m, pd = D - 2 * m;
  ctx.strokeRect(X(m), Y(D - m), pw * s, pd * s);
  ctx.setLineDash([]);

  // 占位
  ctx.font = "11px sans-serif";
  for (const p of placements) {
    const x = X(p.x_mm), y = Y(p.y_mm + p.depth_mm);
    ctx.fillStyle = colorFor(p.model_id) + (state.solution?.valid ? "cc" : "88");
    ctx.fillRect(x, y, p.width_mm * s, p.depth_mm * s);
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, p.width_mm * s, p.depth_mm * s);
    const label = `${p.name} #${p.index}${p.rotation ? " ↻90" : ""}`;
    if (p.width_mm * s > 60 && p.depth_mm * s > 16) {
      ctx.fillStyle = "#0f172a";
      ctx.fillText(label, x + 4, y + 13);
    }
  }

  // 原点与尺寸标注
  ctx.fillStyle = "#475569";
  ctx.fillText("(0,0)", X(0) - 18, Y(0) + 14);
  ctx.fillText(`${fmt(W)} mm`, X(W / 2) - 24, Y(0) + 14);
  ctx.save();
  ctx.translate(X(0) - 10, Y(D / 2) + 26);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${fmt(D)} mm`, 0, 0);
  ctx.restore();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// 事件绑定
document.getElementById("config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    state = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        bed_width_mm: Number(document.getElementById("bed_width_mm").value),
        bed_depth_mm: Number(document.getElementById("bed_depth_mm").value),
        margin_mm: Number(document.getElementById("margin_mm").value),
        gap_mm: Number(document.getElementById("gap_mm").value),
      }),
    });
    render();
    toast("参数已保存，旧排布已标记失效");
  } catch (err) { toast(err.message); }
});

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = document.getElementById("stl-file").files[0];
  if (!file) return toast("请选择 STL 文件");
  const fd = new FormData();
  fd.append("file", file);
  fd.append("copies", document.getElementById("copies").value);
  try {
    state = await api("/api/models", { method: "POST", body: fd });
    render();
    toast(`已上传 ${file.name}`);
  } catch (err) { toast(err.message, 7000); }
});

document.getElementById("solve-btn").addEventListener("click", async () => {
  try {
    state = await api("/api/solve", { method: "POST" });
    render();
  } catch (err) {
    toast(err.message, 8000);
    state = await refresh();
    render();
  }
});

document.getElementById("export-btn").addEventListener("click", () => {
  // 直接访问下载接口；若已失效，后端返回 409，读取错误提示
  fetch("/api/export").then(async res => {
    if (!res.ok) {
      const j = await res.json().catch(() => null);
      throw new Error(j?.error || `导出失败（HTTP ${res.status}）`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "layout.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }).catch(err => toast(err.message, 6000));
});

(async () => {
  state = await refresh();
  render();
})();

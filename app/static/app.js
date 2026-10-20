// Second Screen client: subscribes to /api/stream and renders the pitch,
// overlay cues, stats and the per-viewer feed.

const $ = (sel) => document.querySelector(sel);
const canvas = $("#pitch");
const ctx = canvas.getContext("2d");
const W = canvas.width, H = canvas.height, SX = W / 105, SY = H / 68;

const LABEL = {
  en: { pre: "Pre-match", h1: "1st half", h2: "2nd half", ft: "Full-time", why: "Why it matters" },
  es: { pre: "Previa", h1: "1er tiempo", h2: "2º tiempo", ft: "Final", why: "Por qué importa" },
};

let teams = [];
let match = null;
let source = null;
let trails = [];
let ball = { x: 52.5, y: 34 };
let lang = "en";
let lastScore = { home: 0, away: 0 };

const L = (k) => (LABEL[lang] || LABEL.en)[k];
const teamById = (id) => (match ? (match.home.id === id ? match.home : match.away) : teams.find((t) => t.id === id));

// ---------------------------------------------------------------- setup
async function init() {
  teams = await (await fetch("/api/teams")).json();
  const opts = teams.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  $("#home").innerHTML = opts;
  $("#away").innerHTML = opts;
  $("#away").value = teams[1].id;
  $("#favTeam").innerHTML = `<option value="">None</option>` + opts;
  const fillPlayers = () => {
    const ids = [$("#home").value, $("#away").value];
    $("#favPlayer").innerHTML =
      `<option value="">None</option>` +
      teams
        .filter((t) => ids.includes(t.id))
        .flatMap((t) => t.players.filter((p) => p.position !== "GK").map((p) => `<option value="${p.id}">${p.name} (${t.short_name})</option>`))
        .join("");
  };
  $("#home").onchange = $("#away").onchange = fillPlayers;
  fillPlayers();
  drawPitch();

  document.querySelectorAll(".tabs button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll(".tabs button, .tab").forEach((el) => el.classList.remove("active"));
      b.classList.add("active");
      $(`#tab-${b.dataset.tab}`).classList.add("active");
    })
  );
  $("#setup").addEventListener("submit", (e) => {
    e.preventDefault();
    start(new FormData(e.target));
  });
  try {
    const health = await (await fetch("/healthz")).json();
    $("#model").textContent = health.model === "offline" ? "AI: offline templates (no model connected)" : `AI: ${health.model} on Microsoft Foundry`;
  } catch {}
}

// ---------------------------------------------------------------- stream
function start(form) {
  if (source) source.close();
  const params = new URLSearchParams(form);
  if (params.get("home") === params.get("away")) return alert("Pick two different clubs");
  params.set("seed", String(Math.floor(Math.random() * 10000)));
  lang = params.get("lang");
  for (const id of ["tab-feed", "tab-commentary", "tab-recap", "tab-trace", "overlays"]) $(`#${id}`).innerHTML = "";
  trails = [];
  lastScore = { home: 0, away: 0 };
  $("#go").textContent = "Restart";

  source = new EventSource(`/api/stream?${params}`);
  source.addEventListener("meta", (e) => onMeta(JSON.parse(e.data)));
  source.addEventListener("event", (e) => onEvent(JSON.parse(e.data)));
  source.addEventListener("state", (e) => onState(JSON.parse(e.data)));
  source.addEventListener("cue", (e) => onCue(JSON.parse(e.data)));
  source.addEventListener("line", (e) => onLine(JSON.parse(e.data)));
  source.addEventListener("recap", (e) => onRecap(JSON.parse(e.data)));
  source.addEventListener("trace", (e) => onTrace(JSON.parse(e.data)));
  source.addEventListener("end", () => { source.close(); $("#period").textContent = L("ft"); });
}

function onMeta({ match: m, model }) {
  match = m;
  const css = document.documentElement.style;
  css.setProperty("--home", m.home.colors[0]);
  css.setProperty("--away", m.away.colors[0]);
  $(".team.home .name").textContent = m.home.name;
  $(".team.away .name").textContent = m.away.name;
  $("#period").textContent = L("h1");
  $("#model").textContent = model === "offline" ? "AI: offline templates (no model connected)" : `AI: ${model} on Microsoft Foundry`;
}

function onEvent(e) {
  $("#clock").textContent = `${String(e.minute).padStart(2, "0")}:${String(e.second).padStart(2, "0")}`;
  const color = teamById(e.team_id)?.colors[0] || "#fff";
  if (e.end_x != null) {
    trails.push({ x: e.x, y: e.y, ex: e.end_x, ey: e.end_y, type: e.type, ok: e.outcome !== "incomplete", color, born: performance.now() });
    ball = { x: e.end_x, y: e.end_y };
  } else if (e.x != null) {
    if (["tackle", "interception", "ball_recovery"].includes(e.type)) trails.push({ x: e.x, y: e.y, type: "def", color, born: performance.now() });
    ball = { x: e.x, y: e.y };
  }
  trails = trails.slice(-14);
}

function onState(s) {
  const h = s.teams[s.home_id], a = s.teams[s.away_id];
  $("#gh").textContent = s.score.home;
  $("#ga").textContent = s.score.away;
  if (s.score.home !== lastScore.home || s.score.away !== lastScore.away) {
    $(".goals").classList.remove("flash");
    void $(".goals").offsetWidth;
    $(".goals").classList.add("flash");
    lastScore = s.score;
  }
  $("#period").textContent = s.finished ? L("ft") : s.period === 1 ? L("h1") : L("h2");
  const tiltH = s.last_5_min[s.home_id]?.field_tilt ?? 0.5;
  $("#tiltHome").style.width = `${Math.round(tiltH * 100)}%`;
  $("#tiltAway").style.width = `${Math.round((1 - tiltH) * 100)}%`;

  const pct = (v) => `${Math.round(v * 100)}%`;
  const rows = [
    ["Possession", pct(h.possession), pct(a.possession), h.possession, a.possession],
    ["xG", h.xg.toFixed(2), a.xg.toFixed(2), h.xg, a.xg],
    ["Shots (on target)", `${h.shots} (${h.shots_on_target})`, `${a.shots} (${a.shots_on_target})`, h.shots, a.shots],
    ["Pass accuracy", pct(h.pass_accuracy), pct(a.pass_accuracy), h.pass_accuracy, a.pass_accuracy],
    ["Progressive passes", h.progressive_passes, a.progressive_passes, h.progressive_passes, a.progressive_passes],
    ["PPDA (lower = more press)", h.ppda ?? "–", a.ppda ?? "–", a.ppda || 1, h.ppda || 1],
  ];
  $("#stats").innerHTML = rows
    .map(([k, hv, av, hn, an]) => {
      const tot = hn + an || 1;
      return `<div class="stat"><div class="k">${k}</div><div class="v"><span>${hv}</span><span>${av}</span></div><div class="bar"><i style="width:${(hn / tot) * 100}%"></i><i style="width:${(an / tot) * 100}%"></i></div></div>`;
    })
    .join("");
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function onCue(c) {
  const chips = (c.stat_chips || []).map((x) => `<span class="chip">${esc(x.label)}: ${esc(x.value)}</span>`).join("");
  const el = document.createElement("div");
  el.className = `cue ${c.layout}`;
  el.style.setProperty("--c1", c.colors?.[0] || "#38f2a4");
  el.dir = c.language === "ar" ? "rtl" : "auto";
  el.innerHTML = `<span class="tag">${esc(c.theme?.replace("_", " "))}${c.player_tag ? " · " + esc(c.player_tag) : ""}</span><span class="title">${esc(c.title)}</span><span class="body">${esc(c.body)}</span>${chips ? `<span class="chips">${chips}</span>` : ""}`;
  const layer = $("#overlays");
  layer.querySelectorAll(`.cue.${c.layout}`).forEach((old) => old.remove());
  layer.appendChild(el);
  const speed = Number(new URLSearchParams(source.url.split("?")[1]).get("speed")) || 30;
  const ms = Math.max(3500, Math.min(9000, (c.duration_s * 1000 * 30) / speed));
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, ms);

  const feed = $("#tab-feed");
  feed.querySelector(".empty")?.remove();
  const item = document.createElement("div");
  item.className = `item ${c.layout === "full_banner" ? "big" : ""}`;
  item.style.setProperty("--c1", c.colors?.[0]);
  item.dir = "auto";
  item.innerHTML = `<div class="meta"><span>${c.minute}'</span><span>${esc(teamById(c.team_id)?.short_name)}</span></div><div class="title">${esc(c.title)}</div><div>${esc(c.body)}</div>${chips ? `<details><summary>${L("why")}</summary><div class="chips">${chips}</div></details>` : ""}`;
  feed.prepend(item);
}

function onLine(l) {
  const el = document.createElement("div");
  el.className = "line";
  el.textContent = l.line;
  $("#tab-commentary").prepend(el);
}

function onRecap(r) {
  $("#tab-recap .empty")?.remove();
  const el = document.createElement("div");
  el.className = "recap";
  el.dir = "auto";
  el.innerHTML = `<h3>${esc(r.title)}</h3><p>${esc(r.summary)}</p>${r.player_of_the_match ? `<p><b>Player of the match:</b> ${esc(r.player_of_the_match)}</p>` : ""}<ul>${(r.key_moments || []).map((k) => `<li>${esc(k)}</li>`).join("")}</ul>`;
  $("#tab-recap").prepend(el);
}

function onTrace(t) {
  if (t.agent === "analyst" && t.importance < 0.45) return;
  const el = document.createElement("div");
  el.className = "trace";
  const detail = t.type || t.theme || t.profile || t.phase || (t.ungrounded ? `ungrounded: ${t.ungrounded.join(", ")}` : "") || t.reason || "";
  el.innerHTML = `<b>${esc(t.agent)}</b> <span class="${esc(t.action)}">${esc(t.action)}</span> ${esc(detail)}`;
  const tab = $("#tab-trace");
  tab.prepend(el);
  while (tab.children.length > 200) tab.lastChild.remove();
}

// ---------------------------------------------------------------- pitch
function drawPitch() {
  for (let i = 0; i < 10; i++) {
    ctx.fillStyle = i % 2 ? "#124831" : "#0f3d2a";
    ctx.fillRect((i * W) / 10, 0, W / 10 + 1, H);
  }
  ctx.strokeStyle = "rgba(255,255,255,.55)";
  ctx.lineWidth = 2;
  ctx.strokeRect(10, 10, W - 20, H - 20);
  ctx.beginPath(); ctx.moveTo(W / 2, 10); ctx.lineTo(W / 2, H - 10); ctx.stroke();
  ctx.beginPath(); ctx.arc(W / 2, H / 2, 9.15 * SX, 0, Math.PI * 2); ctx.stroke();
  for (const left of [true, false]) {
    const x0 = left ? 10 : W - 10, dir = left ? 1 : -1;
    ctx.strokeRect(Math.min(x0, x0 + dir * 16.5 * SX), (34 - 20.16) * SY, 16.5 * SX, 40.32 * SY);
    ctx.strokeRect(Math.min(x0, x0 + dir * 5.5 * SX), (34 - 9.16) * SY, 5.5 * SX, 18.32 * SY);
  }
}

function frame(now) {
  drawPitch();
  for (const tr of trails) {
    const age = (now - tr.born) / 4000;
    if (age > 1) continue;
    ctx.globalAlpha = 1 - age;
    if (tr.type === "def") {
      ctx.fillStyle = "#ff5d6c";
      ctx.beginPath(); ctx.arc(tr.x * SX, tr.y * SY, 7, 0, Math.PI * 2); ctx.fill();
      continue;
    }
    ctx.strokeStyle = tr.type === "shot" ? "#ffcf4a" : tr.color;
    ctx.lineWidth = tr.type === "shot" ? 4 : 2.5;
    ctx.setLineDash(tr.ok ? [] : [6, 6]);
    ctx.beginPath(); ctx.moveTo(tr.x * SX, tr.y * SY); ctx.lineTo(tr.ex * SX, tr.ey * SY); ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#fff";
  ctx.shadowColor = "rgba(0,0,0,.6)"; ctx.shadowBlur = 8;
  ctx.beginPath(); ctx.arc(ball.x * SX, ball.y * SY, 8, 0, Math.PI * 2); ctx.fill();
  ctx.shadowBlur = 0;
  requestAnimationFrame(frame);
}

init();
requestAnimationFrame(frame);

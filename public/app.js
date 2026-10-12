"use strict";

const POLL_MS = 60_000;        // how often an open page checks for new stories
const TICK_MS = 15_000;        // how often relative times ("5m ago") refresh
const NEW_BADGE_MS = 5 * 60_000;
const PAGE = 60;               // cards shown per "show more" step
const HOURS = [1, 3, 12, 24, 48];
const TOPIC_KEYS = ["politics", "business", "security", "tech", "science_health", "energy_climate"];
const REGION_KEYS = ["all", "uae", "middle_east", "world"];

const L = {
  en: {
    brand: "Live News Brief", refresh: "Refresh", searchPh: "Search headlines…", uaeOnly: "Mentions the UAE", unread: "Unread only",
    all: "All", latest: "Latest", top: "Top", topic: "Topic", sources: "Sources", saved: "Saved", bell: "Alerts", bellOn: "Alerts on",
    hours: ["Last hour", "Last 3 hours", "Last 12 hours", "Last 24 hours", "Last 48 hours"],
    regions: { all: "All news", uae: "UAE", middle_east: "Middle East", world: "World" },
    topics: { politics: "Politics", business: "Business", security: "Security & Defense", tech: "Tech", science_health: "Science & Health", energy_climate: "Energy & Climate" },
    live: s => `Live · updated ${s}`, stale: s => `Updated ${s} — retrying`, error: "Could not load the news. Retrying automatically.",
    empty: "No stories match these filters.", emptySaved: "Nothing saved yet. Tap ☆ on a story to keep it here.",
    newStories: n => `${n} new ${n === 1 ? "story" : "stories"} — tap to show`, count: (n, t) => `${n} of ${t} stories`, savedCount: n => `${n} saved ${n === 1 ? "story" : "stories"}`,
    ago: { now: "just now", m: n => `${n}m ago`, h: n => `${n}h ago`, d: n => `${n}d ago` }, newTag: "NEW", uaeTag: "UAE", watchTag: t => `Watching: ${t}`,
    trending: "Trending now", trendNone: "Not enough stories yet", watchlist: "Watchlist", watchPh: "+ Watch a keyword", watchHint: "Add a name or topic and matching stories get highlighted.",
    pulse: "Stories per hour (24h)", pulseFrom: "24h ago", pulseTo: "now", pulseTip: (n, h) => `${n} stories · ${h}:00`,
    more: n => `Show ${n} more`, open: "Open article", save: "Save", unsave: "Saved", copy: "Copy link", copied: "Link copied", share: "Share", mute: "Hide this source", muted: s => `Hidden: ${s}`,
    alsoBy: n => `Also reported by ${n} ${n === 1 ? "outlet" : "outlets"}`, related: "Related stories", covered: n => `${n + 1} outlets`,
    srcAll: "All", srcNone: "None", srcShown: (a, b) => `${a} of ${b} sources`, saveToast: "Saved for later", unsaveToast: "Removed from saved",
    alertsUnsupported: "Notifications aren't supported in this browser", alertsBlocked: "Notifications are blocked in your browser settings", alertsOn: "Alerts on — you'll be notified of watchlist matches",
    alertsOff: "Alerts off", slowDown: "Slow down a little — try again in a few seconds", srcHealth: (a, b) => `${a}/${b} sources responding`, srcFailed: "Not responding", watchHits: n => `${n} new ${n === 1 ? "story matches" : "stories match"} your watchlist`,
    helpTitle: "Keyboard shortcuts", keys: [["/", "Search"], ["j / k", "Next / previous story"], ["Enter", "Open story panel"], ["s", "Save / unsave"], ["o", "Open original article"], ["r", "Refresh now"], ["l", "Switch grid / list"], ["t", "Switch light / dark"], ["Esc", "Close panel"], ["?", "This help"]],
  },
  ar: {
    brand: "موجز الأخبار المباشر", refresh: "تحديث", searchPh: "ابحث في العناوين…", uaeOnly: "تذكر الإمارات", unread: "غير المقروءة فقط",
    all: "الكل", latest: "الأحدث", top: "الأهم", topic: "الموضوع", sources: "المصادر", saved: "المحفوظة", bell: "التنبيهات", bellOn: "التنبيهات مفعّلة",
    hours: ["آخر ساعة", "آخر 3 ساعات", "آخر 12 ساعة", "آخر 24 ساعة", "آخر 48 ساعة"],
    regions: { all: "كل الأخبار", uae: "الإمارات", middle_east: "الشرق الأوسط", world: "العالم" },
    topics: { politics: "السياسة", business: "الأعمال", security: "الأمن والدفاع", tech: "التقنية", science_health: "العلوم والصحة", energy_climate: "الطاقة والمناخ" },
    live: s => `مباشر · آخر تحديث ${s}`, stale: s => `آخر تحديث ${s} — إعادة المحاولة`, error: "تعذر تحميل الأخبار. تتم إعادة المحاولة تلقائيا.",
    empty: "لا توجد أخبار مطابقة لهذه الفلاتر.", emptySaved: "لا شيء محفوظ بعد. اضغط ☆ على أي خبر لحفظه هنا.",
    newStories: n => `${n} ${n === 1 ? "خبر جديد" : "أخبار جديدة"} — اضغط للعرض`, count: (n, t) => `${n} من ${t} خبرا`, savedCount: n => `${n} من الأخبار المحفوظة`,
    ago: { now: "الآن", m: n => `منذ ${n} د`, h: n => `منذ ${n} س`, d: n => `منذ ${n} يوم` }, newTag: "جديد", uaeTag: "الإمارات", watchTag: t => `تتابع: ${t}`,
    trending: "الأكثر تداولا الآن", trendNone: "لا توجد أخبار كافية بعد", watchlist: "قائمة المتابعة", watchPh: "+ تابع كلمة", watchHint: "أضف اسما أو موضوعا وسيتم تمييز الأخبار المطابقة.",
    pulse: "الأخبار في كل ساعة (24 ساعة)", pulseFrom: "قبل 24 ساعة", pulseTo: "الآن", pulseTip: (n, h) => `${n} خبرا · ${h}:00`,
    more: n => `عرض ${n} أخرى`, open: "فتح الخبر الأصلي", save: "حفظ", unsave: "محفوظ", copy: "نسخ الرابط", copied: "تم نسخ الرابط", share: "مشاركة", mute: "إخفاء هذا المصدر", muted: s => `تم إخفاء: ${s}`,
    alsoBy: n => `نشره أيضا ${n} ${n === 1 ? "مصدر" : "مصادر"}`, related: "أخبار ذات صلة", covered: n => `${n + 1} مصادر`,
    srcAll: "الكل", srcNone: "لا شيء", srcShown: (a, b) => `${a} من ${b} مصدرا`, saveToast: "تم الحفظ", unsaveToast: "أزيل من المحفوظات",
    alertsUnsupported: "المتصفح لا يدعم الإشعارات", alertsBlocked: "الإشعارات محظورة في إعدادات المتصفح", alertsOn: "التنبيهات مفعّلة — ستصلك إشعارات عند مطابقة قائمة المتابعة",
    alertsOff: "التنبيهات متوقفة", slowDown: "تمهّل قليلا — حاول بعد ثوان", srcHealth: (a, b) => `${a}/${b} مصدرا يعمل`, srcFailed: "لا يستجيب", watchHits: n => `${n} من الأخبار الجديدة تطابق قائمة متابعتك`,
    helpTitle: "اختصارات لوحة المفاتيح", keys: [["/", "بحث"], ["j / k", "الخبر التالي / السابق"], ["Enter", "فتح لوحة الخبر"], ["s", "حفظ / إلغاء الحفظ"], ["o", "فتح الخبر الأصلي"], ["r", "تحديث الآن"], ["l", "تبديل الشبكة / القائمة"], ["t", "تبديل الفاتح / الداكن"], ["Esc", "إغلاق اللوحة"], ["?", "هذه المساعدة"]],
  },
};

const STOP = new Set(("the a an and or of to in on for with at by from as is are was were be been it its this that these those after before over under amid into about says said will would could should may might has have had not new more than their his her they them our your you we he she who what when where why how all also but just up out off per via vs " +
  "في من على إلى عن مع هذا هذه ذلك التي الذي التى الى أن إن كان كانت قال قالت بعد قبل أمام خلال حول بين ضد عند كما لكن ثم أو و").split(" "));

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem("lnb." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("lnb." + k, JSON.stringify(v)); } catch { /* storage may be blocked */ } },
};

const state = {
  lang: store.get("lang", (navigator.language || "en").toLowerCase().startsWith("ar") ? "ar" : "en"),
  theme: store.get("theme", matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"),
  layout: store.get("layout", "grid"),
  region: store.get("region", "all"), topics: new Set(store.get("topics", [])), uaeOnly: store.get("uaeOnly", false),
  unreadOnly: store.get("unreadOnly", false), hours: store.get("hours", 24), sort: store.get("sort", "latest"), q: "",
  hiddenSources: new Set(store.get("hiddenSources", [])), watch: store.get("watch", []), alerts: store.get("alerts", false),
  saved: new Map(store.get("saved", [])), read: new Set(store.get("read", [])),
  showSaved: false, bucket: null, limit: PAGE, selId: null, drawerId: null, list: [],
  health: null, items: new Map(), seen: new Set(), pending: [], freshUntil: new Map(), updatedAt: 0, failing: false, loaded: false,
};
const t = () => L[state.lang];

// ------------------------------------------------------------------ data
async function load({ manual = false } = {}) {
  if (manual) $("refresh").classList.add("spin");
  try {
    const res = await fetch("/api/news" + (manual ? "?t=" + Date.now() : ""), { cache: "no-store" });
    if (res.status === 429) { toast(t().slowDown); throw new RangeError("rate limited"); }
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    state.health = data.health || null;
    ingest(data.items || []);
    state.updatedAt = Date.now(); state.failing = false;
  } catch (e) { if (!(e instanceof RangeError)) state.failing = true; }
  $("refresh").classList.remove("spin");
  update(); renderLive();
}

function ingest(list) {
  const incoming = list.filter(i => i.id && i.title);
  if (!state.loaded) {
    incoming.forEach(i => { state.items.set(i.id, i); state.seen.add(i.id); });
    state.loaded = true; return;
  }
  const fresh = [];
  for (const i of incoming) {
    const old = state.items.get(i.id);
    if (old) { state.items.set(i.id, { ...old, ...i, image: i.image || old.image, summary: old.summary || i.summary }); continue; }
    state.items.set(i.id, i);
    if (!state.seen.has(i.id)) fresh.push(i);
    state.seen.add(i.id);
  }
  const shown = fresh.filter(i => matches(i, { ignorePending: true }));
  state.pending.push(...shown);
  const hits = fresh.filter(i => watchHits(i).length);
  if (hits.length) notifyWatch(hits);
}

function showPending() {
  const now = Date.now();
  state.pending.forEach(i => state.freshUntil.set(i.id, now + NEW_BADGE_MS));
  state.pending = []; state.limit = PAGE; update(); window.scrollTo({ top: 0, behavior: "smooth" });
}

// ------------------------------------------------------------------ filtering
const ts = i => (i.published ? Date.parse(i.published) : 0);
const watchHits = i => { const hay = (i.title + " " + (i.summary || "")).toLowerCase(); return state.watch.filter(w => hay.includes(w.toLowerCase())); };

function matches(i, { ignoreTime = false, ignorePending = false } = {}) {
  if (!ignorePending && state.pending.some(p => p.id === i.id)) return false;
  if (state.hiddenSources.has(i.source)) return false;
  if (state.region !== "all" && i.region !== state.region) return false;
  if (state.uaeOnly && !i.uae) return false;
  if (state.topics.size && !i.topics.some(x => state.topics.has(x))) return false;
  if (state.unreadOnly && state.read.has(i.id)) return false;
  if (!ignoreTime) {
    if (state.bucket !== null) { const p = ts(i); if (p < state.bucket || p >= state.bucket + 3600_000) return false; }
    else if (i.published && Date.now() - ts(i) > state.hours * 3600_000) return false;
  }
  if (state.q) {
    const hay = (i.title + " " + i.source + " " + (i.summary || "")).toLowerCase();
    if (!state.q.split(/\s+/).every(w => hay.includes(w))) return false;
  }
  return true;
}

function visibleItems() {
  if (state.showSaved) {
    const q = state.q ? state.q.split(/\s+/) : [];
    return [...state.saved.values()].map(s => ({ ...s, ...(state.items.get(s.id) || {}), savedAt: s.savedAt }))
      .filter(i => q.every(w => (i.title + " " + i.source).toLowerCase().includes(w)))
      .sort((a, b) => b.savedAt - a.savedAt);
  }
  const list = [...state.items.values()].filter(i => matches(i));
  if (state.sort === "top") {
    const rank = i => i.score + (i.also?.length || 0) * 2 - Math.max(0, (Date.now() - ts(i)) / 3600_000) * 0.35 + (i.uae ? 6 : 0) + (watchHits(i).length ? 12 : 0);
    list.sort((a, b) => rank(b) - rank(a));
  } else list.sort((a, b) => ts(b) - ts(a));
  return list;
}

// ------------------------------------------------------------------ helpers
const agoText = iso => {
  if (!iso) return "";
  const m = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60000)), a = t().ago;
  return m < 2 ? a.now : m < 60 ? a.m(m) : m < 1440 ? a.h(Math.floor(m / 60)) : a.d(Math.floor(m / 1440));
};
const hue = s => { let h = 0; for (const c of s || "") h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const gradient = source => { const h = hue(source); return `--c1:hsl(${h} 38% 24%);--c2:hsl(${(h + 40) % 360} 30% 12%)`; };
const tokens = s => (s.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(w => w.length > (/[؀-ۿ]/.test(w) ? 2 : 3) && !STOP.has(w) && !/^\d+$/.test(w));
function persistFilters() {
  ["lang", "theme", "layout", "region", "uaeOnly", "unreadOnly", "hours", "sort", "watch", "alerts"].forEach(k => store.set(k, state[k]));
  store.set("topics", [...state.topics]);
  store.set("hiddenSources", [...state.hiddenSources]);
}
const persistUser = () => { store.set("saved", [...state.saved].slice(-200)); store.set("read", [...state.read].slice(-3000)); };

let toastTimer;
function toast(msg) { const el = $("toast"); el.textContent = msg; el.classList.add("on"); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("on"), 2400); }

// ------------------------------------------------------------------ cards
function card(i) {
  const el = document.createElement("div");
  const fresh = (state.freshUntil.get(i.id) || 0) > Date.now(), hits = watchHits(i);
  el.className = "card" + (state.read.has(i.id) ? " read" : "") + (fresh ? " fresh" : "") + (hits.length ? " watchhit" : "") + (state.selId === i.id ? " sel" : "");
  el.tabIndex = 0; el.setAttribute("role", "button"); el.dataset.id = i.id;
  const tags = [i.uae ? `<span class="tag uae">${t().uaeTag}</span>` : "", fresh ? `<span class="tag new">${t().newTag}</span>` : "",
    hits.length ? `<span class="tag watch">${esc(t().watchTag(hits[0]))}</span>` : ""].join("");
  const isSaved = state.saved.has(i.id), cov = i.also?.length || 0;
  el.innerHTML = `
    <div class="img" style="${gradient(i.source)}">
      <div class="ph">${esc((i.source || "?").trim().charAt(0).toUpperCase())}</div>
      ${i.image ? `<img alt="" loading="lazy" referrerpolicy="no-referrer" src="${esc(i.image)}">` : ""}
      <div class="badge">${tags}</div>
      <button class="save${isSaved ? " on" : ""}" aria-label="${t().save}" title="${t().save} (s)">${isSaved ? "★" : "☆"}</button>
    </div>
    <div class="body">
      <div class="src"><span>${esc(i.source)}</span><span class="t" data-ago="${i.published || ""}">${agoText(i.published)}</span>${cov ? `<span class="cov">· ${t().covered(cov)}</span>` : ""}</div>
      <h3 dir="auto">${esc(i.title)}</h3>
      ${i.summary ? `<p class="sum" dir="auto">${esc(i.summary)}</p>` : ""}
      <div class="tops">${i.topics.map(x => `<span>${t().topics[x] || x}</span>`).join("")}</div>
    </div>`;
  const img = el.querySelector("img");
  if (img) { img.onload = () => img.classList.add("ok"); img.onerror = () => { img.remove(); queueEnrich(i, el); }; } else queueEnrich(i, el);
  return el;
}

function render() {
  const grid = $("grid"), list = state.list = visibleItems();
  const held = state.pending.length;
  document.title = (held ? `(${held}) ` : "") + t().brand;
  $("banner").style.display = held ? "block" : "none";
  $("bannerBtn").textContent = t().newStories(held);
  grid.className = "grid" + (state.layout === "list" ? " list" : "");
  $("savedBtn").setAttribute("aria-pressed", state.showSaved); $("savedCount").textContent = state.saved.size;
  if (!state.loaded) {
    grid.innerHTML = state.failing ? `<div class="err" style="grid-column:1/-1">${t().error}</div>` : `<div class="skeleton"></div>`.repeat(6);
    $("meta").textContent = ""; $("moreBtn").hidden = true; return;
  }
  const h = state.health, text = state.showSaved ? t().savedCount(list.length) : t().count(list.length, state.items.size);
  const warn = h && h.total && h.ok / h.total < 0.7, failed = h?.failed?.length ? `${t().srcFailed}: ${h.failed.join(", ")}` : "";
  $("meta").innerHTML = esc(text) + (h && h.total ? ` <span class="health${warn ? " warn" : ""}" title="${esc(failed)}">· ${esc(t().srcHealth(h.ok, h.total))}</span>` : "");
  const shown = list.slice(0, state.limit);
  const nodes = shown.map((i, n) => { const c = card(i); if (n === 0 && state.layout === "grid" && innerWidth > 640 && !state.showSaved) c.classList.add("lead"); return c; });
  grid.replaceChildren(...(nodes.length ? nodes : [Object.assign(document.createElement("div"), { className: "empty", textContent: state.showSaved ? t().emptySaved : t().empty, style: "grid-column:1/-1" })]));
  const rest = list.length - shown.length;
  $("moreBtn").hidden = rest <= 0; $("moreBtn").textContent = t().more(Math.min(rest, PAGE));
  renderInsights();
}

function renderLive() {
  const age = state.updatedAt ? Math.round((Date.now() - state.updatedAt) / 1000) : null, ar = state.lang === "ar";
  const label = age === null ? "…" : age < 5 ? (ar ? "الآن" : "now") : age < 60 ? (ar ? `قبل ${age} ث` : `${age}s ago`) : (ar ? `قبل ${Math.floor(age / 60)} د` : `${Math.floor(age / 60)}m ago`);
  $("live").className = "live" + (state.failing ? " error" : age !== null && age > 180 ? " stale" : "");
  $("liveText").textContent = state.failing ? t().stale(label) : t().live(label);
}

// ------------------------------------------------------------------ insights: trending, watchlist, pulse
function renderInsights() {
  $("trendTitle").textContent = t().trending; $("watchTitle").textContent = t().watchlist; $("pulseTitle").textContent = t().pulse;
  const windowed = [...state.items.values()].filter(i => (!i.published || Date.now() - ts(i) <= state.hours * 3600_000) && !state.hiddenSources.has(i.source));
  const counts = new Map();
  for (const i of windowed) for (const w of new Set(tokens(i.title))) counts.set(w, (counts.get(w) || 0) + 1);
  const top = [...counts].filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1] || b[0].length - a[0].length).slice(0, 10);
  $("trending").replaceChildren(...(top.length ? top.map(([w, n]) => {
    const b = document.createElement("button"); b.className = "kw"; b.innerHTML = `${esc(w)}<b>${n}</b>`;
    b.onclick = () => { state.q = state.q === w ? "" : w; $("q").value = state.q; state.limit = PAGE; render(); };
    return b;
  }) : [Object.assign(document.createElement("span"), { className: "label", textContent: t().trendNone })]));

  const wl = state.watch.map(w => {
    const b = document.createElement("span"); b.className = "kw watch"; b.textContent = w;
    const x = Object.assign(document.createElement("button"), { className: "x", textContent: "✕", title: "Remove", onclick: () => { state.watch = state.watch.filter(v => v !== w); persistFilters(); render(); } });
    b.append(x); return b;
  });
  const add = Object.assign(document.createElement("input"), { type: "text", className: "watch-add", placeholder: t().watchPh, title: t().watchHint });
  add.onkeydown = e => { if (e.key === "Enter" && add.value.trim()) { const v = add.value.trim(); if (!state.watch.some(w => w.toLowerCase() === v.toLowerCase())) state.watch.push(v); persistFilters(); render(); $("watchlist").querySelector("input")?.focus(); } };
  $("watchlist").replaceChildren(...wl, add);

  const base = [...state.items.values()].filter(i => matches(i, { ignoreTime: true }) && i.published);
  const nowHour = Math.floor(Date.now() / 3600_000) * 3600_000, buckets = Array.from({ length: 24 }, (_, n) => nowHour - (23 - n) * 3600_000);
  const vals = buckets.map(b => base.filter(i => ts(i) >= b && ts(i) < b + 3600_000).length), max = Math.max(1, ...vals);
  $("pulse").replaceChildren(...buckets.map((b, n) => {
    const col = document.createElement("div"); col.className = "bar-col" + (state.bucket === b ? " on" : ""); col.style.height = Math.max(6, (vals[n] / max) * 100) + "%";
    col.title = t().pulseTip(vals[n], new Date(b).getHours().toString().padStart(2, "0"));
    col.onclick = () => { state.bucket = state.bucket === b ? null : b; state.limit = PAGE; render(); };
    return col;
  }));
  $("pulseFrom").textContent = t().pulseFrom; $("pulseTo").textContent = t().pulseTo;
}

// ------------------------------------------------------------------ chrome (static controls)
function chip(text, n, on, onclick) {
  const b = document.createElement("button"); b.className = "chip"; b.setAttribute("aria-pressed", on); b.onclick = onclick;
  b.innerHTML = esc(text) + (n === null ? "" : `<span class="n">${n}</span>`); return b;
}
function renderChrome() {
  document.documentElement.lang = state.lang; document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr"; document.documentElement.dataset.theme = state.theme;
  $("brand").textContent = t().brand; $("refreshText").textContent = t().refresh; $("q").placeholder = t().searchPh; $("uaeLabel").textContent = t().uaeOnly; $("unreadLabel").textContent = t().unread;
  $("savedText").textContent = t().saved; $("bellBtn").textContent = (state.alerts ? "🔔 " : "🔕 ") + (state.alerts ? t().bellOn : t().bell); $("bellBtn").classList.toggle("on", state.alerts);
  $("layoutBtn").textContent = state.layout === "grid" ? "☰" : "▦"; $("themeBtn").textContent = state.theme === "dark" ? "☀" : "☾";
  document.querySelectorAll("#langSeg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.lang === state.lang));
  const all = [...state.items.values()];
  $("regions").replaceChildren(...REGION_KEYS.map(r => chip(t().regions[r], r === "all" ? all.length : all.filter(i => i.region === r).length, state.region === r, () => { state.region = r; state.limit = PAGE; persistFilters(); update(); })));
  $("topics").replaceChildren(Object.assign(document.createElement("span"), { className: "label", textContent: t().topic }),
    chip(t().all, null, state.topics.size === 0, () => { state.topics.clear(); state.limit = PAGE; persistFilters(); update(); }),
    ...TOPIC_KEYS.map(k => chip(t().topics[k], all.filter(i => i.topics.includes(k)).length, state.topics.has(k), () => { state.topics.has(k) ? state.topics.delete(k) : state.topics.add(k); state.limit = PAGE; persistFilters(); update(); })));
  $("hours").replaceChildren(...HOURS.map((h, n) => Object.assign(document.createElement("option"), { value: h, textContent: t().hours[n], selected: h === state.hours })));
  $("sortSeg").replaceChildren(...["latest", "top"].map(s => Object.assign(document.createElement("button"), { textContent: t()[s], onclick: () => { state.sort = s; persistFilters(); update(); } })));
  [...$("sortSeg").children].forEach((b, n) => b.setAttribute("aria-pressed", ["latest", "top"][n] === state.sort));
  $("uaeOnly").checked = state.uaeOnly; $("unreadOnly").checked = state.unreadOnly;
  renderSources();
}
function update() { renderChrome(); render(); if (state.drawerId) renderDrawer(); }

function renderSources() {
  const counts = new Map(); state.items.forEach(i => counts.set(i.source, (counts.get(i.source) || 0) + 1));
  const names = [...counts].sort((a, b) => b[1] - a[1]);
  const shown = names.filter(([s]) => !state.hiddenSources.has(s)).length;
  $("srcBtn").textContent = `${t().sources} · ${t().srcShown(shown, names.length)}`;
  const panel = $("srcPanel");
  if (panel.hidden) return;
  const head = document.createElement("div"); head.className = "ph";
  head.innerHTML = `<button data-a="all">${t().srcAll}</button><button data-a="none">${t().srcNone}</button>`;
  head.onclick = e => { const a = e.target.dataset?.a; if (!a) return; state.hiddenSources = a === "all" ? new Set() : new Set(names.map(([s]) => s)); persistFilters(); update(); };
  panel.replaceChildren(head, ...names.map(([s, n]) => {
    const l = document.createElement("label"); l.innerHTML = `<input type="checkbox" ${state.hiddenSources.has(s) ? "" : "checked"}><span>${esc(s)}</span><span class="c">${n}</span>`;
    l.querySelector("input").onchange = e => { e.target.checked ? state.hiddenSources.delete(s) : state.hiddenSources.add(s); persistFilters(); const top = panel.scrollTop; update(); panel.scrollTop = top; };
    return l;
  }));
}

// ------------------------------------------------------------------ lazy images / publisher links
const enrichCache = new Map(), enrichQueue = []; let enrichActive = 0;
const io = new IntersectionObserver(entries => entries.forEach(e => { if (e.isIntersecting) { io.unobserve(e.target); enrichQueue.push(e.target); pump(); } }), { rootMargin: "400px" });
function queueEnrich(item, el) { if (enrichCache.has(item.id)) return; el._item = item; io.observe(el); }
function enrich(item) {
  if (!enrichCache.has(item.id)) {
    enrichCache.set(item.id, fetch("/api/enrich?u=" + encodeURIComponent(item.link)).then(r => r.ok ? r.json() : null).catch(() => null).then(d => {
      const cur = state.items.get(item.id);
      if (d && cur) { cur.image = d.image || cur.image; if (d.url) cur.link = d.url; if (!cur.summary && d.summary) cur.summary = d.summary; }
      return d;
    }));
  }
  return enrichCache.get(item.id);
}
async function pump() {
  while (enrichActive < 4 && enrichQueue.length) {
    const el = enrichQueue.shift(), i = el._item; if (!i || enrichCache.has(i.id)) continue;
    enrichActive++;
    enrich(i).then(d => {
      if (d?.image && el.isConnected && !el.querySelector(".img img")) {
        const img = Object.assign(document.createElement("img"), { alt: "", referrerPolicy: "no-referrer", src: d.image });
        img.onload = () => img.classList.add("ok"); el.querySelector(".img").prepend(img);
      }
      if (state.drawerId === i.id) renderDrawer();
    }).finally(() => { enrichActive--; pump(); });
  }
}

// ------------------------------------------------------------------ story panel
function findItem(id) { return state.items.get(id) || state.saved.get(id) || state.list.find(i => i.id === id); }
function related(item) {
  const a = new Set(tokens(item.title)); if (a.size < 3) return [];
  return [...state.items.values()].filter(o => o.id !== item.id).map(o => { const b = new Set(tokens(o.title)); const inter = [...a].filter(w => b.has(w)).length; return [o, inter / (a.size + b.size - inter)]; })
    .filter(([, s]) => s >= 0.18).sort((x, y) => y[1] - x[1]).slice(0, 4).map(([o]) => o);
}
function openDrawer(id) {
  state.drawerId = id; state.selId = id; markRead(id);
  renderDrawer(); $("drawer").classList.add("on"); $("drawer").setAttribute("aria-hidden", "false"); $("scrim").classList.add("on");
  const item = findItem(id); if (item && !item.image) enrich(item).then(() => { if (state.drawerId === id) renderDrawer(); });
  document.querySelectorAll(".card").forEach(c => c.classList.toggle("sel", c.dataset.id === id));
}
function closeDrawer() { state.drawerId = null; $("drawer").classList.remove("on"); $("drawer").setAttribute("aria-hidden", "true"); $("scrim").classList.remove("on"); }
function renderDrawer() {
  const i = findItem(state.drawerId); if (!i) return closeDrawer();
  const hits = watchHits(i), isSaved = state.saved.has(i.id), rel = related(i);
  $("dBody").innerHTML = `
    <div class="d-img" style="${gradient(i.source)}">${i.image ? `<img alt="" referrerpolicy="no-referrer" src="${esc(i.image)}" onerror="this.remove()">` : ""}</div>
    <div class="d-main">
      <div class="src"><span>${esc(i.source)}</span><span class="t">${agoText(i.published)}</span>${i.uae ? `<span class="tag uae">${t().uaeTag}</span>` : ""}${hits.length ? `<span class="tag watch" style="background:var(--gold);color:var(--gold-ink)">${esc(t().watchTag(hits[0]))}</span>` : ""}</div>
      <h2 dir="auto">${esc(i.title)}</h2>
      ${i.summary ? `<p dir="auto">${esc(i.summary)}</p>` : ""}
      <div class="tops" style="margin-bottom:8px">${i.topics.map(x => `<span>${t().topics[x] || x}</span>`).join("")}</div>
      <div class="d-actions">
        <a class="btn primary" href="${esc(i.link)}" target="_blank" rel="noopener noreferrer" id="dOpen">${t().open} ↗</a>
        <button class="btn" id="dSave">${isSaved ? "★ " + t().unsave : "☆ " + t().save}</button>
        <button class="btn" id="dCopy">${t().copy}</button>
        ${navigator.share ? `<button class="btn" id="dShare">${t().share}</button>` : ""}
        <button class="btn" id="dMute">${t().mute}</button>
      </div>
    </div>
    ${i.also?.length ? `<div class="d-sec"><h4>${t().alsoBy(i.also.length)}</h4>${i.also.map(a => `<a class="d-link" href="${esc(a.link)}" target="_blank" rel="noopener noreferrer"><small>${esc(a.source)}</small><span dir="auto">${esc(a.title)}</span></a>`).join("")}</div>` : ""}
    ${rel.length ? `<div class="d-sec"><h4>${t().related}</h4>${rel.map(r => `<a class="d-link" href="#" data-open="${r.id}"><small>${esc(r.source)} · ${agoText(r.published)}</small><span dir="auto">${esc(r.title)}</span></a>`).join("")}</div>` : ""}`;
  $("dOpen").onclick = () => markRead(i.id);
  $("dSave").onclick = () => toggleSave(i.id);
  $("dCopy").onclick = () => copyLink(i.link);
  $("dShare")?.addEventListener("click", () => navigator.share({ title: i.title, url: i.link }).catch(() => {}));
  $("dMute").onclick = () => { state.hiddenSources.add(i.source); persistFilters(); toast(t().muted(i.source)); closeDrawer(); update(); };
  $("dBody").querySelectorAll("[data-open]").forEach(a => a.onclick = e => { e.preventDefault(); openDrawer(a.dataset.open); $("dBody").scrollTop = 0; });
}
function step(delta) {
  const list = state.list; if (!list.length) return;
  const cur = list.findIndex(i => i.id === (state.drawerId || state.selId)), next = Math.min(list.length - 1, Math.max(0, cur + delta));
  const id = list[next].id; state.selId = id;
  if (next >= state.limit - 1 && state.limit < list.length) { state.limit += PAGE; render(); }
  if (state.drawerId) openDrawer(id);
  else { document.querySelectorAll(".card").forEach(c => c.classList.toggle("sel", c.dataset.id === id)); document.querySelector(`.card[data-id="${id}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }); }
}

// ------------------------------------------------------------------ actions
function markRead(id) { if (!state.read.has(id)) { state.read.add(id); persistUser(); document.querySelector(`.card[data-id="${id}"]`)?.classList.add("read"); } }
function toggleSave(id) {
  const item = findItem(id); if (!item) return;
  if (state.saved.has(id)) { state.saved.delete(id); toast(t().unsaveToast); } else { state.saved.set(id, { ...item, savedAt: Date.now() }); toast(t().saveToast); }
  persistUser(); update();
}
async function copyLink(url) { try { await navigator.clipboard.writeText(url); } catch { const ta = Object.assign(document.createElement("textarea"), { value: url }); document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); } toast(t().copied); }

async function toggleAlerts() {
  if (!("Notification" in window)) return toast(t().alertsUnsupported);
  if (state.alerts) { state.alerts = false; persistFilters(); update(); return toast(t().alertsOff); }
  const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  if (perm !== "granted") return toast(t().alertsBlocked);
  state.alerts = true; persistFilters(); update(); toast(t().alertsOn);
}
function notifyWatch(hits) {
  toast(t().watchHits(hits.length));
  if (state.alerts && "Notification" in window && Notification.permission === "granted") {
    new Notification(hits[0].title, { body: `${hits[0].source}${hits.length > 1 ? " +" + (hits.length - 1) : ""}`, tag: "lnb-watch" });
  }
}

function showHelp() {
  $("helpCard").innerHTML = `<h3>${t().helpTitle}</h3>` + t().keys.map(([k, d]) => `<div class="krow"><span>${d}</span><span>${k.split(" / ").map(x => `<kbd>${x}</kbd>`).join(" ")}</span></div>`).join("");
  $("helpModal").hidden = false;
}

// ------------------------------------------------------------------ wiring
$("grid").addEventListener("click", e => {
  const c = e.target.closest(".card"); if (!c) return;
  if (e.target.closest(".save")) return toggleSave(c.dataset.id);
  openDrawer(c.dataset.id);
});
$("grid").addEventListener("keydown", e => { if (e.key === "Enter" && e.target.classList.contains("card")) openDrawer(e.target.dataset.id); });
$("moreBtn").onclick = () => { state.limit += PAGE; render(); };
$("langSeg").onclick = e => { const l = e.target.dataset?.lang; if (l) { state.lang = l; persistFilters(); update(); renderLive(); } };
$("q").oninput = e => { state.q = e.target.value.trim().toLowerCase(); state.limit = PAGE; render(); };
$("uaeOnly").onchange = e => { state.uaeOnly = e.target.checked; persistFilters(); render(); };
$("unreadOnly").onchange = e => { state.unreadOnly = e.target.checked; persistFilters(); render(); };
$("hours").onchange = e => { state.hours = +e.target.value; state.bucket = null; persistFilters(); render(); };
$("refresh").onclick = () => load({ manual: true });
$("bannerBtn").onclick = showPending;
$("savedBtn").onclick = () => { state.showSaved = !state.showSaved; state.limit = PAGE; render(); };
$("bellBtn").onclick = toggleAlerts;
$("layoutBtn").onclick = () => { state.layout = state.layout === "grid" ? "list" : "grid"; persistFilters(); update(); };
$("themeBtn").onclick = () => { state.theme = state.theme === "dark" ? "light" : "dark"; persistFilters(); renderChrome(); };
$("helpBtn").onclick = showHelp;
$("helpModal").onclick = e => { if (e.target === $("helpModal")) $("helpModal").hidden = true; };
$("srcBtn").onclick = e => { e.stopPropagation(); $("srcPanel").hidden = !$("srcPanel").hidden; renderSources(); };
document.addEventListener("click", e => { if (!e.target.closest(".pop")) $("srcPanel").hidden = true; });
$("scrim").onclick = closeDrawer; $("dClose").onclick = closeDrawer;
$("dPrev").onclick = () => step(-1); $("dNext").onclick = () => step(1);

document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (e.key === "Escape") { if (!$("helpModal").hidden) $("helpModal").hidden = true; else if (state.drawerId) closeDrawer(); else if (typing) document.activeElement.blur(); return; }
  if (typing) return;
  // Shortcuts act on the page, not on whichever button was clicked last (Enter would re-press it).
  if (document.activeElement && document.activeElement !== document.body && !document.activeElement.classList.contains("card")) document.activeElement.blur();
  const id = state.drawerId || state.selId;
  switch (e.key) {
    case "/": e.preventDefault(); $("q").focus(); break;
    case "j": step(1); break;
    case "k": step(-1); break;
    case "Enter": if (id && !state.drawerId && !document.activeElement.classList.contains("card")) openDrawer(id); break;
    case "s": if (id) toggleSave(id); break;
    case "o": { const item = id && findItem(id); if (item) { markRead(id); window.open(item.link, "_blank", "noopener"); } break; }
    case "r": load({ manual: true }); break;
    case "l": $("layoutBtn").click(); break;
    case "t": $("themeBtn").click(); break;
    case "?": showHelp(); break;
  }
});

setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
setInterval(() => { document.querySelectorAll("[data-ago]").forEach(n => n.textContent = agoText(n.dataset.ago)); renderLive(); }, TICK_MS);
document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - state.updatedAt > 30_000) load(); });

renderChrome(); render(); load();

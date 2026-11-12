// Photo → topics → four editable texts. All writes use the existing same-origin boundary.
(function () {
  "use strict";
  const root = document.querySelector("[data-create]");
  if (!root) { return; }
  const C = JSON.parse(root.dataset.create), T = C.strings;
  const $ = (selector, inRoot = root) => inRoot.querySelector(selector);
  const all = (selector, inRoot = root) => Array.from(inRoot.querySelectorAll(selector));
  let busy = false, recording = false, disposed = false;
  let navigate = url => window.location.assign(url);
  const report = (el, message) => { el.textContent = message; };
  function error(message, retry) {
    let el = $(".create-error") || $(".create-status");
    if (!el) { return; }
    el.hidden = false;
    el.replaceChildren();
    const p = document.createElement("p");
    p.textContent = message;
    el.appendChild(p);
    el.classList.add("k-bad");
    el.setAttribute("role", "alert");
    if (retry) {
      const button = document.createElement("button");
      button.className = "btn"; button.type = "button"; button.textContent = T.repeat;
      button.addEventListener("click", retry); el.appendChild(button);
    }
  }
  async function post(path, data, type = "application/json") {
    let resp;
    try {
      resp = await fetch(path, {method: "POST", credentials: "same-origin",
        headers: {"Content-Type": type, "X-CSRF-Token": C.csrf},
        body: type === "application/json" ? JSON.stringify(data) : data});
    } catch (_) { throw new Error(T.network); }
    let result;
    try { result = await resp.json(); } catch (_) { throw new Error(T.network); }
    if (result.month) {
      const m = document.getElementById("ai-month");
      m.textContent = result.month;
    }
    if (!resp.ok) { throw new Error(result.error || String(resp.status)); }
    return result;
  }
  function setBusy(value) {
    busy = value;
    all("button, input", root).forEach(b => {
      if (b.matches("[data-op]")) {
        b.disabled = value || (recording && b.dataset.op !== "voice") || !!C.why[b.dataset.op] || (b.dataset.op === "expand" && !$("#topic").value.trim());
      } else if (b.matches(".topic-card, [data-recent], #create-file")) { b.disabled = value; }
    });
    root.setAttribute("aria-busy", String(value));
    const hint = $(".topic-hint");
    if (hint) { hint.hidden = !!$("#topic").value.trim(); }
    const drop = $(".create-drop");
    if (drop) { drop.classList.toggle("busy", value); }
  }
  async function newDraft(folder, photo) {
    report($(".create-status"), T.drafting);
    const result = await post("/create/new", {folder, photo});
    navigate(result.url);
    return result;
  }
  async function drop(files) {
    if (busy) { return; }
    if (files.length !== 1) { error(T.many); return; }
    setBusy(true); report($(".create-status"), T.uploading);
    try {
      const p = await window.MFAuthor.uploadFile("my-photos", C.csrf, files[0]);
      await newDraft("my-photos", p.id);
    } catch (err) { error(err.message); }
    finally { setBusy(false); }
  }
  window.MFCreate = {drop, navigate: fn => { navigate = fn; }};
  if (!C.draft) {
    const zone = $(".create-drop"), file = $("#create-file"), hint = $(".drop-hint");
    const originalHint = hint.textContent;
    window.addEventListener("dragover", e => e.preventDefault());
    window.addEventListener("drop", e => e.preventDefault());
    zone.addEventListener("dragover", e => {
      e.preventDefault(); if (busy) { return; }
      zone.classList.add("dragover"); hint.textContent = T.drop;
    });
    zone.addEventListener("dragleave", () => { zone.classList.remove("dragover"); hint.textContent = originalHint; });
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("dragover"); hint.textContent = originalHint;
      drop(Array.from(e.dataTransfer.files));
    });
    file.addEventListener("change", () => { if (file.files.length) { drop(Array.from(file.files)); } file.value = ""; });
    all("[data-recent]").forEach(b => b.addEventListener("click", async () => {
      if (busy) { return; }
      setBusy(true);
      try { await newDraft(b.dataset.folder, b.dataset.recent); } catch (err) { error(err.message); }
      finally { setBusy(false); }
    }));
    return;
  }
  let activeError = C.draft.error && C.draft.error.op;
  const D = C.draft, base = "/create/" + D.id;
  const topic = $("#topic");
  const pending = new Set();
  const savers = new Map();
  function resize(el) { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; }
  function saver(el, path, payload, status, after) {
    let timer, serial = Promise.resolve();
    async function flush() {
      clearTimeout(timer); timer = null;
      if (el.value === el.dataset.saved) { return serial; }
      const value = el.value;
      report(status, T.saving);
      serial = serial.catch(() => {}).then(async () => {
        const result = await post(base + path, payload(value));
        el.dataset.saved = value;
        if (el.value === value) { status.classList.remove("k-bad"); report(status, T.saved); if (after) { after(result); } }
        return result;
      }).catch(err => { report(status, err.message); status.classList.add("k-bad"); throw err; });
      const tracked = serial;
      pending.add(tracked);
      tracked.finally(() => pending.delete(tracked)).catch(() => {});
      return serial;
    }
    el.dataset.saved = el.value;
    el.addEventListener("input", () => {
      resize(el); clearTimeout(timer); status.classList.remove("k-bad");
      timer = setTimeout(() => flush().catch(() => {}), 800);
    });
    savers.set(el, flush);
    resize(el);
    return flush;
  }
  const saveTopic = saver(topic, "/topic", value => ({topic: value}), $(".topic-save"));
  topic.addEventListener("input", () => {
    const count = $(".topic-count"); count.hidden = topic.value.length < 1800;
    count.textContent = topic.value.length + "/2000"; markChosen(); setBusy(busy);
  });
  function markChosen() {
    all(".topic-card").forEach(b => {
      const chosen = b.dataset.topic === topic.value;
      b.setAttribute("aria-pressed", String(chosen)); $(".chosen", b).textContent = chosen ? T.chosen : "";
    });
  }
  function bindTopic(b) {
    b.addEventListener("click", async () => {
      topic.value = b.dataset.topic; resize(topic); markChosen(); setBusy(busy);
      try { await saveTopic(); } catch (_) { /* the saver keeps the text and reason */ }
    });
  }
  function renderTopics(topics) {
    D.topics = topics;
    const container = $(".topic-cards"); container.replaceChildren();
    topics.forEach(item => {
      const b = document.createElement("button"); b.type = "button"; b.className = "topic-card";
      b.dataset.topic = item.title + " — " + item.angle;
      [["strong", item.title], ["span", item.angle], ["span", ""]].forEach(([tag, text], i) => {
        const span = document.createElement(tag); span.textContent = text;
        if (i === 2) { span.className = "chosen"; } b.appendChild(span);
      });
      container.appendChild(b); bindTopic(b);
    });
    $("[data-op=topics]").textContent = (topics.length ? T.more_topics : T.topics) + " · " + C.bounds.topics;
    markChosen();
  }
  all(".topic-card").forEach(bindTopic);
  function check(card, result) {
    const box = $(".text-check", card); box.replaceChildren();
    function line(parent, message, cls) {
      const p = document.createElement("p"); p.className = cls || ""; p.textContent = message; parent.appendChild(p);
    }
    result.counts.forEach(c => line(box, c, "mono small"));
    if (result.errors.length) {
      const errors = document.createElement("div"); errors.className = "k-bad text-errors"; errors.setAttribute("role", "alert");
      const m = (result.counts[0] || "").match(/(\d+)\/(\d+)/);
      if (m && +m[1] > +m[2]) { line(errors, T.over + m[0]); }
      result.errors.forEach(e => line(errors, T.problem + " " + e)); box.appendChild(errors);
    }
  }
  function expandLabel() {
    $("[data-op=expand]").textContent = (Object.values(D.variants).some(v => v.source === "edited") ?
      T.expand_again : T.expand) + " · " + C.bounds.expand;
  }
  function bindText(card) {
    const n = card.dataset.network, el = $(".text-editor", card);
    saver(el, "/text", value => ({network: n, text: value}), $(".save-status", card), result => {
      D.variants[n] = {text: el.value, lang: n === "x" || n === "linkedin" ? "en" : "uk", source: "edited"};
      check(card, result); expandLabel();
    });
    $("[data-op=regenerate]", card).addEventListener("click", () => ai("regenerate", {network: n, wish: $(".wish", card).value}));
  }
  function renderTexts(variants, only) {
    if (only) { D.variants[only] = variants[only]; } else { D.variants = variants; }
    const container = $(".text-cards");
    all(".text-editor", container).forEach(el => {
      if (!only || el.closest(".create-text").dataset.network === only) { savers.delete(el); }
    });
    if (!only) { container.replaceChildren(); }
    Object.keys(C.networks).forEach(n => {
      if (!variants[n] || (only && n !== only)) { return; }
      const card = document.createElement("article"); card.className = "create-text"; card.dataset.network = n;
      const h = document.createElement("h3"); h.textContent = C.networks[n];
      const el = document.createElement("textarea"); el.className = "text-editor"; el.value = variants[n].text;
      el.setAttribute("aria-label", C.networks[n]);
      const box = document.createElement("div"); box.className = "text-check";
      const saved = document.createElement("p"); saved.className = "save-status small"; saved.setAttribute("role", "status");
      const row = document.createElement("div"); row.className = "regenerate-row";
      const wish = document.createElement("input"); wish.className = "wish"; wish.maxLength = 200;
      wish.placeholder = T.wish; wish.setAttribute("aria-label", T.wish + " " + C.networks[n]);
      const b = document.createElement("button"); b.type = "button"; b.className = "btn"; b.dataset.op = "regenerate";
      b.textContent = T.regenerate + " · " + C.bounds.regenerate;
      b.title = C.why.regenerate || ""; b.disabled = !!C.why.regenerate;
      row.append(wish, b); card.append(h, el, box, saved, row);
      const old = only && container.querySelector('[data-network="' + n + '"]');
      if (old) { old.replaceWith(card); } else { container.appendChild(card); }
      check(card, variants[n]); bindText(card);
    });
    expandLabel();
  }
  all(".create-text").forEach(bindText);
  async function ai(op, data = {}, audio, mime) {
    if (busy) { return; }
    if (C.why[op]) { error(C.why[op]); return; }
    setBusy(true);
    const line = op === "regenerate" ? $(".text-ai-status") : $(".ai-status");
    const message = op === "topics" ? T.topics_loading : op === "voice" ? T.transcribing : T.expand_loading;
    report(line, message);
    const writing = op === "expand" ? all(".text-editor") : op === "regenerate" ?
      all('[data-network="' + data.network + '"] .text-editor') : [];
    writing.forEach(el => { el.readOnly = true; });
    try {
      if (op === "voice") { await saveTopic(); }
      if (op === "expand" || op === "regenerate") {
        await saveTopic();
        await Promise.all(Array.from(savers.entries()).filter(([el]) => el !== topic).map(([, flush]) => flush()));
      }
      const result = await post(base + "/" + op, audio || data, mime || "application/json");
      if (activeError === op) { $(".create-error").hidden = true; activeError = ""; }
      if (op === "topics") { renderTopics(result.topics); }
      if (result.variants) { renderTexts(result.variants, op === "regenerate" ? data.network : ""); }
      if (op === "voice") {
        if (topic.value !== topic.dataset.saved) {
          topic.value = (topic.value + " " + result.transcript).trim();
          await saveTopic();
        } else { topic.value = result.topic; topic.dataset.saved = result.topic; }
        resize(topic); markChosen();
        voiceBlob = null; report($(".voice-status"), T.saved);
      }
      if (op === "expand") { document.getElementById("texts").scrollIntoView({block: "start"}); }
      return result;
    } catch (err) {
      activeError = op;
      // The automatic topics request is spent once on the server; a retry is a real request.
      error(err.message, op === "voice" ? null : () => ai(op, op === "topics" ? {} : data, audio, mime));
      if (op === "voice") { showVoiceRetry(); }
    } finally { writing.forEach(el => { el.readOnly = false; }); report(line, ""); setBusy(false); }
  }
  $("[data-op=topics]").addEventListener("click", () => ai("topics"));
  $("[data-op=expand]").addEventListener("click", () => ai("expand"));
  all("[data-retry]").forEach(b => b.addEventListener("click", () => ai(b.dataset.retry, {network: b.dataset.network})));
  const voice = $("[data-op=voice]");
  let recorder, stream, chunks = [], voiceBlob, voiceMime, started, ticker, stopping = false;
  function mediaType() {
    if (!window.MediaRecorder) { return ""; }
    return ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find(t => MediaRecorder.isTypeSupported(t)) || "";
  }
  function showVoiceRetry() {
    const line = $(".voice-status"); line.replaceChildren();
    const b = document.createElement("button"); b.type = "button"; b.className = "btn"; b.textContent = T.voice_retry;
    b.addEventListener("click", () => ai("voice", {}, voiceBlob, voiceMime)); line.appendChild(b);
  }
  function stopTracks() { if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; } }
  function stopVoice(send = true) {
    clearInterval(ticker);
    if (recorder && recorder.state !== "inactive") { stopping = !send; recorder.stop(); }
    recording = false;
    stopTracks(); voice.textContent = T.voice; voice.setAttribute("aria-pressed", "false");
  }
  function tick() {
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const time = Math.floor(elapsed / 60) + ":" + String(elapsed % 60).padStart(2, "0");
    voice.textContent = T.stop + " · " + time; report($(".voice-status"), time);
    if (elapsed >= 120) { stopVoice(); }
  }
  voice.addEventListener("click", async () => {
    if (recorder && recorder.state === "recording") { stopVoice(); return; }
    if (busy) { return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { report($(".voice-status"), T.voice_context); return; }
    const mime = mediaType();
    if (!mime) { report($(".voice-status"), T.voice_unsupported); return; }
    setBusy(true);
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      if (disposed) { stopTracks(); return; }
      recorder = new MediaRecorder(stream, {mimeType: mime, audioBitsPerSecond: 32000}); chunks = []; stopping = false;
      recorder.ondataavailable = e => { if (e.data.size) { chunks.push(e.data); } };
      recorder.onstop = async () => {
        if (stopping) { return; }
        voiceMime = mime.split(";")[0]; voiceBlob = new Blob(chunks, {type: voiceMime}); chunks = [];
        await ai("voice", {}, voiceBlob, voiceMime);
      };
      recorder.onerror = () => { stopVoice(false); report($(".voice-status"), T.voice_unsupported); };
      recorder.start(); recording = true; started = Date.now(); ticker = setInterval(tick, 200); tick();
      voice.setAttribute("aria-pressed", "true");
    } catch (err) {
      stopTracks(); report($(".voice-status"), err.name === "NotAllowedError" ? T.voice_denied :
        err.name === "NotFoundError" ? T.voice_missing : T.voice_unsupported);
    } finally { setBusy(false); }
  });
  window.addEventListener("pagehide", () => { disposed = true; stopVoice(false); });
  window.MFCreate.ai = ai;
  window.MFCreate.flush = async () => { await Promise.all(Array.from(savers.values()).map(flush => flush())); await Promise.all(pending); };
  window.MFCreate.stopVoice = stopVoice;
  if (D.topics_auto === "pending") { ai("topics", {auto: true}); }
  setBusy(busy);
})();

const CHARS_PER_PAGE = 1150;
const REQUEST_TIMEOUT_MS = 300000;

const UPLOAD_STAGE_META = {
  queued: {
    title: "Upload queued",
    description: "The file has been accepted and is waiting for the background pipeline to start.",
  },
  "extract-source-text": {
    title: "Extracting source text",
    description: "Reading the uploaded file and extracting plain text from the source document.",
  },
  "segment-chapters": {
    title: "Segmenting chapters",
    description: "Detecting chapter boundaries and preparing paragraph-level source units.",
  },
  "construct-episodes": {
    title: "Constructing episodes",
    description: "Building constrained extraction packets from adjacent source paragraphs.",
  },
  "graph-episode-start": {
    title: "Processing episode",
    description: "Preparing the current packet for entity and fact extraction.",
  },
  "llm-skipped": {
    title: "LLM gate skipped this packet",
    description: "The gate judged this packet low-value, so the graph used the non-LLM path here.",
  },
  "llm-request-dispatched": {
    title: "Waiting for LLM extraction",
    description: "The packet prompt has been sent to the configured graph extraction model.",
  },
  "llm-response-received": {
    title: "LLM extraction received",
    description: "The extraction model has returned structured entity and fact candidates.",
  },
  "llm-request-failed": {
    title: "LLM extraction failed",
    description: "The graph extraction step failed for the current packet.",
  },
  "graph-episode-complete": {
    title: "Episode graph updated",
    description: "The current packet has been written back into the temporal graph state.",
  },
  "chapter-consolidation": {
    title: "Chapter consolidation",
    description: "Merging aliases, deduplicating relations, and reconciling chapter-level graph state.",
  },
  "graph-community-build": {
    title: "Building communities",
    description: "Clustering entities and relations into graph communities.",
  },
  "graph-saga-build": {
    title: "Building sagas",
    description: "Aggregating chapter-level developments into larger narrative sagas.",
  },
  "graph-timeline-build": {
    title: "Building chapter timeline",
    description: "Assembling the chapter timeline from visible episodes, entities, and facts.",
  },
  "graph-build-finished": {
    title: "Graph build finished",
    description: "The graph build is complete and is moving into persistence steps.",
  },
  "persist-book-record": {
    title: "Persisting book record",
    description: "Saving the parsed book record to local storage.",
  },
  "persist-graph-snapshot": {
    title: "Persisting graph snapshot",
    description: "Saving the full graph snapshot, including relations, communities, and sagas.",
  },
  "finalize-upload": {
    title: "Finalizing upload",
    description: "Wrapping up upload metadata and preparing the book for reading.",
  },
  completed: {
    title: "Temporal graph ready",
    description: "The upload, extraction, and temporal graph construction pipeline has finished.",
  },
  failed: {
    title: "Upload failed",
    description: "The upload pipeline failed before finishing the document and graph build.",
  },
};

const WORKFLOW_META = {
  personaQa: {
    title: "Literary agent answering",
    description: "Reading the visible book scope, retrieving graph context, and generating an answer through the literary agent.",
  },
  characterQa: {
    title: "Character agent answering",
    description: "Reading the visible character scope and generating a role-grounded answer.",
  },
  chapterSummary: {
    title: "Chapter summarization",
    description: "Collecting visible chapter context and generating a grounded chapter summary.",
  },
  characterProfile: {
    title: "Building character profile",
    description: "Gathering evidence, relationships, and current scope notes for the selected character.",
  },
};

const state = {
  books: [],
  personas: [],
  characterCandidates: [],
  activeBook: null,
  activeBookDetail: null,
  activeChapter: 1,
  activeParagraphIndex: null,
  activeChunkId: null,
  activePageIndex: 0,
  assistantMode: "persona",
  personaId: "persona_lu_xun",
  activeCharacterName: "",
  activeCharacterProfile: null,
  personaConversation: [],
  characterConversation: [],
  inlineBubblesByChunk: {},
  pendingWorkflow: null,
  graphViewVisible: false,
  graphViewScope: "chapter",
  graphViewData: null,
  graphViewLoading: false,
  graphViewError: "",
  chapterEnteredAt: Date.now(),
  readingProgress: {
    book_id: "",
    chapter_id: 1,
    section_id: "sec-1",
    paragraph_id: "",
    token_offset: 0,
    scroll_offset: 0,
    dwell_seconds: 0,
    updated_at: "",
  },
  selectionContext: {
    book_id: "",
    selection_id: "",
    selected_text: "",
    left_context: "",
    right_context: "",
    anchor: {
      chapter_id: 1,
      section_id: "sec-1",
      paragraph_id: "",
    },
  },
};

async function fetchJSON(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...options, signal: options.signal || controller.signal });
    if (!response.ok) {
      let detail = `Request failed: ${response.status}`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (_error) {
        // ignore
      }
      throw new Error(detail);
    }
    return response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`Request exceeded ${REQUEST_TIMEOUT_MS / 1000}s.`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function escapeHtml(text = "") {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function previewText(text, fallback = "Nothing is selected yet.") {
  return text && text.trim() ? text.trim() : fallback;
}

function setButtonLoading(buttonId, isLoading, loadingText = "") {
  const button = document.getElementById(buttonId);
  if (!button) {
    return;
  }
  if (!button.dataset.defaultText) {
    button.dataset.defaultText = button.textContent;
  }
  button.disabled = isLoading;
  button.textContent = isLoading ? loadingText : button.dataset.defaultText;
}

function getPersonaById(personaId) {
  return state.personas.find((persona) => persona.persona_id === personaId) || state.personas[0] || null;
}

function getCurrentPassages() {
  if (!state.activeBookDetail) {
    return [];
  }
  return (
    state.activeBookDetail.chapters[String(state.activeChapter)] ||
    state.activeBookDetail.chapters[state.activeChapter] ||
    []
  );
}

function getFirstReadableChapter() {
  if (!state.activeBookDetail) {
    return 1;
  }
  for (let chapter = 1; chapter <= state.activeBookDetail.chapter_count; chapter += 1) {
    const passages = state.activeBookDetail.chapters[String(chapter)] || state.activeBookDetail.chapters[chapter] || [];
    if (passages.length) {
      return chapter;
    }
  }
  return 1;
}

function getCurrentPages() {
  const passages = getCurrentPassages();
  if (!passages.length) {
    return [];
  }
  const pages = [];
  let currentPage = [];
  let currentSize = 0;

  passages.forEach((passage, index) => {
    const estimatedSize = (passage.text || "").length + 80;
    if (currentPage.length && currentSize + estimatedSize > CHARS_PER_PAGE) {
      pages.push(currentPage);
      currentPage = [];
      currentSize = 0;
    }
    currentPage.push({ ...passage, _index: index });
    currentSize += estimatedSize;
  });

  if (currentPage.length) {
    pages.push(currentPage);
  }

  return pages;
}

function getCurrentPageItems() {
  const pages = getCurrentPages();
  if (!pages.length) {
    return [];
  }
  state.activePageIndex = Math.max(0, Math.min(state.activePageIndex, pages.length - 1));
  return pages[state.activePageIndex];
}

function currentConversation() {
  return state.assistantMode === "persona" ? state.personaConversation : state.characterConversation;
}

function pushConversation(role, content) {
  const target = state.assistantMode === "persona" ? state.personaConversation : state.characterConversation;
  target.push({ role, content });
}

function renderPendingWorkflow() {
  const indicator = document.getElementById("pending-indicator");
  const title = document.getElementById("pending-title");
  const label = document.getElementById("pending-label");
  const description = document.getElementById("pending-description");
  const bar = document.getElementById("pending-bar");
  const percent = document.getElementById("pending-percent");
  const caption = document.getElementById("pending-step-caption");

  if (!indicator || !title || !label || !description || !bar || !percent || !caption) {
    return;
  }

  if (!state.pendingWorkflow) {
    indicator.classList.remove("is-active", "is-indeterminate");
    title.textContent = "Idle";
    label.textContent = "idle";
    description.textContent =
      "After a document is uploaded, this panel will display real-time text extraction, packet construction, LLM extraction, and graph persistence progress.";
    bar.style.width = "0%";
    percent.textContent = "0%";
    caption.textContent = "Waiting for the next job to start.";
    return;
  }

  indicator.classList.add("is-active");
  indicator.classList.toggle("is-indeterminate", state.pendingWorkflow.indeterminate === true);
  title.textContent = state.pendingWorkflow.title;
  label.textContent = state.pendingWorkflow.label;
  description.textContent = state.pendingWorkflow.description;
  bar.style.width = state.pendingWorkflow.indeterminate ? "32%" : `${state.pendingWorkflow.percent}%`;
  percent.textContent = `${state.pendingWorkflow.percent}%`;
  caption.textContent = state.pendingWorkflow.caption || "Waiting for the next update.";
}

function setPendingState(active, label = "running", title = "Processing", description = "The task is starting.") {
  if (!active) {
    state.pendingWorkflow = null;
    renderPendingWorkflow();
    return;
  }
  state.pendingWorkflow = {
    label,
    title,
    description,
    percent: 12,
    caption: "Preparing the task pipeline.",
    indeterminate: true,
  };
  renderPendingWorkflow();
}

function startPendingWorkflow(key, label = "running") {
  const meta = WORKFLOW_META[key] || {
    title: "Processing",
    description: "The task is currently running.",
  };
  state.pendingWorkflow = {
    key,
    label,
    title: meta.title,
    description: meta.description,
    percent: 18,
    caption: "Task started.",
    indeterminate: true,
  };
  renderPendingWorkflow();
}

function finishPendingWorkflow(label = "done", title = "Completed", description = "The task finished successfully.") {
  if (!state.pendingWorkflow) {
    return;
  }
  state.pendingWorkflow = {
    ...state.pendingWorkflow,
    label,
    title,
    description,
    percent: 100,
    caption: description,
    indeterminate: false,
  };
  renderPendingWorkflow();
}

function releasePendingState(delayMs = 900) {
  window.setTimeout(() => {
    state.pendingWorkflow = null;
    renderPendingWorkflow();
  }, delayMs);
}

function formatUploadStageCopy(job) {
  const lines = [];
  const processed = Number(job.processed_snippets || 0);
  const total = Number(job.total_snippets || 0);
  const details = job.details || {};

  if (total) {
    lines.push(`Processed snippets: ${processed}/${total}`);
  }
  if (job.current_snippet_id) {
    lines.push(
      `Current snippet: ${job.current_snippet_id} (chapter ${job.current_chapter_index || "-"}, paragraph ${
        job.current_paragraph_index || "-"
      })`
    );
  }
  if (details.source_paragraph_count) {
    const indices = Array.isArray(details.source_paragraph_indices) ? details.source_paragraph_indices : [];
    const span =
      indices.length > 1
        ? `${indices[0]}-${indices[indices.length - 1]}`
        : indices.length === 1
          ? `${indices[0]}`
          : "-";
    lines.push(
      `Packet: paragraphs ${span}, count ${details.source_paragraph_count}, ${
        details.is_merged_packet ? "merged" : "single"
      }, ${details.packet_token_count || 0} chars`
    );
  }
  if (typeof details.score === "number") {
    const reasons = Array.isArray(details.reasons) ? details.reasons.join(", ") : "";
    lines.push(`Gate score: ${details.score}/${details.threshold ?? "-"}${reasons ? ` (${reasons})` : ""}`);
  }
  if (job.stage === "llm-request-dispatched") {
    lines.push(`LLM call dispatched. Provider: ${details.provider || "configured runtime"}`);
  }
  if (job.stage === "llm-response-received") {
    lines.push(`LLM returned ${details.entity_candidates || 0} entity candidates and ${details.fact_candidates || 0} fact candidates.`);
  }
  if (job.stage === "llm-request-failed" && details.error) {
    lines.push(`LLM error: ${details.error}`);
  }
  if (job.stage === "chapter-consolidation") {
    lines.push(
      `Chapter consolidation: entities ${details.active_entity_count || 0}, relations ${details.active_relation_count || 0}`
    );
  }
  if (job.stage === "persist-graph-snapshot") {
    lines.push(
      `Graph snapshot: entities ${details.entity_count || 0}, relations ${details.relation_count || 0}, communities ${
        details.community_count || 0
      }, sagas ${details.saga_count || 0}`
    );
  }
  return lines.join(" | ");
}

function applyUploadJobState(job) {
  const stage = job.stage || job.status || "queued";
  const meta = UPLOAD_STAGE_META[stage] || {
    title: job.title || "Temporal graph build",
    description: job.message || "The upload pipeline is running.",
  };
  state.pendingWorkflow = {
    key: "upload",
    label: stage,
    title: job.title || meta.title,
    description: job.message || meta.description,
    percent: Number(job.percent || 0),
    caption: formatUploadStageCopy(job) || meta.description,
    indeterminate: false,
  };
  renderPendingWorkflow();
}

async function waitForUploadJob(jobId) {
  while (true) {
    const job = await fetchJSON(`/api/upload-jobs/${jobId}`);
    applyUploadJobState(job);
    if (job.status === "completed") {
      return job;
    }
    if (job.status === "failed") {
      throw new Error(job.error || job.message || "Upload job failed.");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
}

function resetSelection() {
  state.selectionContext = {
    book_id: state.activeBook || "",
    selection_id: "",
    selected_text: "",
    left_context: "",
    right_context: "",
    anchor: {
      chapter_id: state.activeChapter,
      section_id: `sec-${state.activeChapter}`,
      paragraph_id: "",
    },
  };
}

function updateProgressFromPassage(passage) {
  const pages = getCurrentPages();
  const scrollOffset = pages.length ? Number(((state.activePageIndex + 1) / pages.length).toFixed(2)) : 0;
  state.readingProgress = {
    book_id: state.activeBook || "",
    chapter_id: state.activeChapter,
    section_id: `sec-${state.activeChapter}`,
    paragraph_id: String(passage.paragraph_index ?? ""),
    token_offset: (passage.text || "").length,
    scroll_offset: scrollOffset,
    dwell_seconds: Math.max(1, Math.floor((Date.now() - state.chapterEnteredAt) / 1000)),
    updated_at: new Date().toISOString(),
  };
}

function buildSelectionFromPassage(passage, index, passages) {
  const previous = passages[index - 1];
  const next = passages[index + 1];
  state.selectionContext = {
    book_id: state.activeBook || "",
    selection_id: `sel_${passage.chunk_id || index + 1}`,
    selected_text: passage.text || "",
    left_context: previous ? previous.text || "" : "",
    right_context: next ? next.text || "" : "",
    anchor: {
      chapter_id: state.activeChapter,
      section_id: `sec-${state.activeChapter}`,
      paragraph_id: String(passage.paragraph_index ?? index + 1),
    },
  };
}

function renderPersonaDetails() {
  const persona = getPersonaById(state.personaId);
  if (!persona) {
    return;
  }
  document.getElementById("persona-type-badge").textContent = persona.source_type;
  document.getElementById("persona-name").textContent = persona.name;
  document.getElementById("persona-citation").textContent = persona.citation || "";
  const traits = document.getElementById("persona-traits");
  traits.innerHTML = "";
  [...(persona.style_traits || []), ...(persona.reasoning_style || [])].slice(0, 6).forEach((item) => {
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = item;
    traits.appendChild(pill);
  });
}

function renderCharacterCandidates() {
  const select = document.getElementById("character-select");
  select.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = state.characterCandidates.length ? "Choose a character candidate" : "No character candidates available";
  select.appendChild(empty);

  state.characterCandidates.forEach((candidate) => {
    const option = document.createElement("option");
    option.value = candidate.character_name;
    option.textContent = `${candidate.character_name} 路 ${candidate.mention_count}`;
    select.appendChild(option);
  });

  if (state.activeCharacterName) {
    select.value = state.activeCharacterName;
  }
}

function renderCharacterProfile() {
  const container = document.getElementById("character-profile-card");
  if (!container) {
    return;
  }
  if (!state.activeCharacterProfile) {
    container.innerHTML = `<p class="muted">Choose a candidate or enter a character name to build a character profile.</p>`;
    return;
  }

  const profile = state.activeCharacterProfile;
  const traits = (profile.core_traits || [])
    .map((trait) => `<span class="pill">${escapeHtml(trait)}</span>`)
    .join("");
  const relationships = (profile.relationships || [])
    .map((relation) => `<li>${escapeHtml(relation.target)} - ${escapeHtml(relation.description)}</li>`)
    .join("");

  container.innerHTML = `
    <h4 class="character-name">${escapeHtml(profile.character_name)}</h4>
    <p class="muted">${escapeHtml(profile.summary || "")}</p>
    <div class="pill-row">${traits}</div>
    <p class="label">Current visible scope</p>
    <p class="muted">${escapeHtml(profile.current_scope || "No visible scope note available.")}</p>
    <p class="label">Signature tension</p>
    <p class="signature-tension">${escapeHtml(profile.signature_tension || "No signature tension note available.")}</p>
    <p class="label">Model</p>
    <p class="muted">${escapeHtml(profile.model_name || "")}</p>
    ${
      relationships
        ? `<p class="label">Relationships</p><ul class="plain-list relationship-list">${relationships}</ul>`
        : ""
    }
  `;
}

function renderBooks() {
  const list = document.getElementById("book-list");
  list.innerHTML = "";
  document.getElementById("book-count").textContent = `${state.books.length} books`;

  state.books.forEach((book) => {
    const item = document.createElement("li");
    item.className = "book-item";
    const button = document.createElement("button");
    button.type = "button";
    button.className = `book-button ${state.activeBook === book.book_id ? "is-active" : ""}`;
    button.innerHTML = `
      <span class="book-title">${escapeHtml(book.title)}</span>
      <span class="book-meta">${escapeHtml(book.book_id)}</span>
    `;
    button.addEventListener("click", () => openBook(book.book_id));
    item.appendChild(button);
    list.appendChild(item);
  });
}

function renderReaderHeader() {
  if (!state.activeBookDetail) {
    document.getElementById("book-title").textContent = "Choose a book to begin";
    document.getElementById("book-subtitle").textContent =
      "Upload a document to inspect chapters, reading progress, and the temporal knowledge graph.";
    document.getElementById("progress-text").textContent = "No reading progress is available yet.";
    document.getElementById("hero-chapter").textContent = "-";
    document.getElementById("hero-paragraph").textContent = "-";
    document.getElementById("hero-dwell").textContent = "0s";
    return;
  }

  const pages = getCurrentPages();
  document.getElementById("book-title").textContent = state.activeBookDetail.title;
  document.getElementById("book-subtitle").textContent = `book_id: ${state.activeBookDetail.book_id} 路 ${state.activeBookDetail.chapter_count} chapters`;
  document.getElementById("progress-text").textContent = `Current position: chapter ${state.readingProgress.chapter_id}, page ${state.activePageIndex + 1}/${pages.length || 0}, paragraph ${state.readingProgress.paragraph_id || "-"}`;
  document.getElementById("hero-chapter").textContent = `Chapter ${state.activeChapter}`;
  document.getElementById("hero-paragraph").textContent =
    state.activeParagraphIndex === null ? "-" : `P${state.activeParagraphIndex}`;
  document.getElementById("hero-dwell").textContent = `${state.readingProgress.dwell_seconds || 0}s`;
}

function renderChapterNav() {
  const container = document.getElementById("chapter-nav");
  container.innerHTML = "";

  if (!state.activeBookDetail) {
    container.innerHTML = `<p class="muted">No chapter outline is available until a book is opened.</p>`;
    return;
  }

  for (let chapter = 1; chapter <= state.activeBookDetail.chapter_count; chapter += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chapter-button ${chapter === state.activeChapter ? "is-active" : ""}`;
    button.textContent = `Chapter ${chapter}`;
    button.addEventListener("click", () => setActiveChapter(chapter));
    container.appendChild(button);
  }

  document.getElementById("toc-progress").textContent = `Reading chapter ${state.activeChapter}`;
}

function renderChapterSelects() {
  const chapterSelect = document.getElementById("chapter-select");
  const paragraphSelect = document.getElementById("paragraph-jump");
  chapterSelect.innerHTML = "";
  paragraphSelect.innerHTML = "";

  if (!state.activeBookDetail) {
    return;
  }

  for (let chapter = 1; chapter <= state.activeBookDetail.chapter_count; chapter += 1) {
    const option = document.createElement("option");
    option.value = String(chapter);
    option.textContent = `Chapter ${chapter}`;
    chapterSelect.appendChild(option);
  }
  chapterSelect.value = String(state.activeChapter);

  getCurrentPassages().forEach((passage, index) => {
    const paragraphIndex = passage.paragraph_index ?? index + 1;
    const option = document.createElement("option");
    option.value = String(paragraphIndex);
    option.textContent = `Paragraph ${paragraphIndex}`;
    paragraphSelect.appendChild(option);
  });

  if (state.activeParagraphIndex !== null) {
    paragraphSelect.value = String(state.activeParagraphIndex);
  }
}

function renderSelectionPreview() {
  document.getElementById("highlight-preview").textContent = previewText(
    state.selectionContext.selected_text,
    "Click a paragraph to preview the selected text and nearby context here."
  );
}

function renderAssistantStatus() {
  const node = document.getElementById("assistant-status");
  if (!node) {
    return;
  }
  if (state.assistantMode === "persona") {
    const persona = getPersonaById(state.personaId);
    node.textContent = persona
      ? `Current mode: literary agent 路 ${persona.name}`
      : "Current mode: literary agent";
    return;
  }
  if (state.activeCharacterProfile) {
    node.textContent = `Current mode: character agent 路 ${state.activeCharacterProfile.character_name}`;
    return;
  }
  if (state.activeCharacterName) {
    node.textContent = `Current mode: character agent 路 ${state.activeCharacterName}`;
    return;
  }
  node.textContent = "Current mode: character agent. Choose or enter a character name to continue.";
}

function renderAssistantMode() {
  document.getElementById("persona-mode-btn").classList.toggle("mode-chip-active", state.assistantMode === "persona");
  document.getElementById("character-mode-btn").classList.toggle("mode-chip-active", state.assistantMode === "character");
  renderAssistantStatus();
  renderChatHistory();
}

function renderChatHistory() {
  const historyNode = document.getElementById("chat-history");
  historyNode.innerHTML = "";
  const conversation = currentConversation();

  if (!conversation.length) {
    historyNode.innerHTML = `<p class="muted">No conversation yet. Ask a question to the current agent.</p>`;
    return;
  }

  conversation.forEach((turn) => {
    const article = document.createElement("article");
    article.className = `chat-message chat-message-${turn.role}`;
    const roleLabel =
      turn.role === "user"
        ? "User"
        : state.assistantMode === "persona"
          ? getPersonaById(state.personaId)?.name || "Literary Agent"
          : state.activeCharacterProfile?.character_name || state.activeCharacterName || "Character Agent";

    article.innerHTML = `
      <div class="chat-role">${escapeHtml(roleLabel)}</div>
      <div class="chat-content">${escapeHtml(turn.content || "").replace(/\n/g, "<br />")}</div>
    `;
    historyNode.appendChild(article);
  });

  historyNode.scrollTop = historyNode.scrollHeight;
}

function updatePageIndicator() {
  const pages = getCurrentPages();
  const total = pages.length;
  const current = total ? state.activePageIndex + 1 : 0;
  document.getElementById("page-indicator").textContent = total ? `${current} / ${total}` : "- / -";
  document.getElementById("prev-page-btn").disabled = current <= 1;
  document.getElementById("next-page-btn").disabled = total === 0 || current >= total;
}

function graphNodeColor(type) {
  if (type === "character") return "#1f6a73";
  if (type === "location") return "#546c44";
  if (type === "theme" || type === "concept") return "#8f5a3c";
  return "#7b6d59";
}

function renderGraphPanel() {
  const panel = document.getElementById("graph-panel");
  const canvas = document.getElementById("graph-canvas");
  const detail = document.getElementById("graph-detail");
  const badge = document.getElementById("graph-stats-badge");
  const caption = document.getElementById("graph-caption");
  const toggleButton = document.getElementById("graph-toggle-btn");
  const chapterScopeButton = document.getElementById("graph-scope-chapter-btn");
  const bookScopeButton = document.getElementById("graph-scope-book-btn");

  chapterScopeButton.classList.toggle("is-active", state.graphViewScope === "chapter");
  bookScopeButton.classList.toggle("is-active", state.graphViewScope === "book");
  panel.classList.toggle("is-hidden", !state.graphViewVisible);
  toggleButton.textContent = state.graphViewVisible ? "Hide Knowledge Graph" : "Show Knowledge Graph";

  if (!state.graphViewVisible) {
    return;
  }

  if (state.graphViewLoading) {
    badge.textContent = "loading";
    canvas.innerHTML = `<p class="muted">Loading graph view...</p>`;
    detail.textContent = "The graph panel is waiting for the backend to return visible nodes and relations.";
    return;
  }

  if (state.graphViewError) {
    badge.textContent = "error";
    canvas.innerHTML = `<p class="muted">${escapeHtml(state.graphViewError)}</p>`;
    detail.textContent = "The graph request failed. Please refresh the graph or verify that the current book has finished graph construction.";
    return;
  }

  const data = state.graphViewData;
  const scopeLabel = state.graphViewScope === "book" ? "whole-book graph" : "current chapter graph";
  if (!data || !Array.isArray(data.nodes) || !data.nodes.length) {
    badge.textContent = "0 nodes";
    canvas.innerHTML = `<p class="muted">No clear graph nodes are available in the ${scopeLabel} yet.</p>`;
    detail.textContent =
      state.graphViewScope === "book"
        ? "The book graph exists, but there are not enough visible nodes or relations to display at the current reading boundary."
        : "The current chapter is sparse. Switch to the whole-book graph if you want a broader view.";
    return;
  }

  badge.textContent = `${data.stats.node_count} nodes / ${data.stats.edge_count} edges`;
  caption.textContent =
    state.graphViewScope === "book"
      ? `Showing the whole-book graph inside the current visible reading scope. Nodes: ${data.stats.node_count}, edges: ${data.stats.edge_count}.`
      : `Showing the current chapter graph for chapter ${data.chapter_index}. Nodes: ${data.stats.node_count}, edges: ${data.stats.edge_count}.`;

  const width = 760;
  const height = 420;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.max(120, Math.min(170, 42 + data.nodes.length * 10));
  const positions = {};

  data.nodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, data.nodes.length);
    positions[node.id] = {
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * Math.min(radius, 130),
    };
  });

  const edgeMarkup = (data.edges || [])
    .map((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      if (!source || !target) {
        return "";
      }
      const midX = (source.x + target.x) / 2;
      const midY = (source.y + target.y) / 2;
      return `
        <g class="graph-edge-group" data-edge-id="${escapeHtml(edge.id)}">
          <line
            class="graph-edge ${edge.status !== "active" ? "is-invalidated" : ""}"
            x1="${source.x}"
            y1="${source.y}"
            x2="${target.x}"
            y2="${target.y}"
            data-edge-id="${escapeHtml(edge.id)}"
          ></line>
          <text class="graph-edge-label" x="${midX}" y="${midY - 6}">${escapeHtml(edge.label)}</text>
        </g>
      `;
    })
    .join("");

  const nodeMarkup = data.nodes
    .map((node) => {
      const position = positions[node.id];
      const size = Math.max(18, Math.min(34, 14 + Math.round((node.mention_count || 0) / 2)));
      return `
        <g class="graph-node" data-node-id="${escapeHtml(node.id)}">
          <circle
            class="graph-node-circle type-${escapeHtml(node.type || "unknown")}"
            cx="${position.x}"
            cy="${position.y}"
            r="${size}"
            fill="${graphNodeColor(node.type)}"
            data-node-id="${escapeHtml(node.id)}"
          ></circle>
          <text class="graph-node-label" x="${position.x}" y="${position.y + size + 14}">${escapeHtml(node.label)}</text>
        </g>
      `;
    })
    .join("");

  const communityMarkup = Array.isArray(data.communities) && data.communities.length
    ? `<div class="graph-community-summary"><strong>Communities:</strong> ${data.communities
        .map((community) => `${escapeHtml(community.label)} (${community.entity_count})`)
        .join(" / ")}</div>`
    : "";

  canvas.innerHTML = `
    <svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="knowledge graph view">
      ${edgeMarkup}
      ${nodeMarkup}
    </svg>
    ${communityMarkup}
  `;

  detail.textContent = "Click a node to inspect the entity summary, or click an edge to inspect the relation.";

  canvas.querySelectorAll("[data-node-id]").forEach((nodeElement) => {
    nodeElement.addEventListener("click", (event) => {
      const nodeId = event.currentTarget.dataset.nodeId;
      const node = data.nodes.find((item) => item.id === nodeId);
      if (!node) {
        return;
      }
      detail.innerHTML = `
        <strong>${escapeHtml(node.label)}</strong> 路 ${escapeHtml(node.type || "entity")}<br />
        Mentions: ${node.mention_count || 0}<br />
        First seen: chapter ${node.first_seen_chapter || "-"}, paragraph ${node.first_seen_paragraph || "-"}<br />
        ${escapeHtml(node.summary || "No summary available for this node.")}
      `;
    });
  });

  canvas.querySelectorAll("[data-edge-id]").forEach((edgeElement) => {
    edgeElement.addEventListener("click", (event) => {
      const edgeId = event.currentTarget.dataset.edgeId;
      const edge = data.edges.find((item) => item.id === edgeId);
      if (!edge) {
        return;
      }
      detail.innerHTML = `
        <strong>${escapeHtml(edge.label)}</strong> 路 ${escapeHtml(edge.state_family || "relation")}<br />
        Valid at: chapter ${edge.valid_at_chapter || "-"}, paragraph ${edge.valid_at_paragraph || "-"}<br />
        Status: ${escapeHtml(edge.status || "unknown")}<br />
        ${escapeHtml(edge.fact || "No fact string is available for this relation.")}
      `;
    });
  });
}

async function refreshKnowledgeGraph() {
  if (!state.activeBook || !state.graphViewVisible) {
    return;
  }
  state.graphViewLoading = true;
  state.graphViewError = "";
  renderGraphPanel();
  try {
    const query = new URLSearchParams({
      chapter: String(state.activeChapter),
      paragraph: String(state.activeParagraphIndex || 0),
      limit: "18",
      scope: state.graphViewScope,
    });
    state.graphViewData = await fetchJSON(`/api/books/${state.activeBook}/graph/view?${query.toString()}`);
  } catch (error) {
    state.graphViewError = error.message;
  } finally {
    state.graphViewLoading = false;
    renderGraphPanel();
  }
}

async function toggleKnowledgeGraph() {
  state.graphViewVisible = !state.graphViewVisible;
  renderGraphPanel();
  if (state.graphViewVisible) {
    await refreshKnowledgeGraph();
  }
}

async function setKnowledgeGraphScope(scope) {
  if (scope !== "chapter" && scope !== "book") {
    return;
  }
  state.graphViewScope = scope;
  renderGraphPanel();
  if (state.graphViewVisible) {
    await refreshKnowledgeGraph();
  }
}

function createInlineBubbleMarkup(text, chunkId) {
  const bubbles = (state.inlineBubblesByChunk[chunkId] || [])
    .map((bubble) => ({ ...bubble, index: text.indexOf(bubble.anchor_text) }))
    .filter((bubble) => bubble.index >= 0)
    .sort((a, b) => a.index - b.index);

  if (!bubbles.length) {
    return escapeHtml(text);
  }

  let cursor = 0;
  let markup = "";
  bubbles.forEach((bubble) => {
    const start = text.indexOf(bubble.anchor_text, cursor);
    if (start < cursor || start < 0) {
      return;
    }
    const end = start + bubble.anchor_text.length;
    markup += escapeHtml(text.slice(cursor, start));
    markup += `
      <span class="inline-bubble" data-bubble-id="${escapeHtml(bubble.bubble_id)}">
        <button
          class="inline-bubble-anchor"
          type="button"
          data-bubble-id="${escapeHtml(bubble.bubble_id)}"
          aria-label="${escapeHtml(bubble.label)}"
        >${escapeHtml(bubble.anchor_text)}</button>
        <span class="inline-bubble-tip" data-bubble-id="${escapeHtml(bubble.bubble_id)}">
          <strong>${escapeHtml(bubble.label)}</strong>${escapeHtml(bubble.comment)}
        </span>
      </span>
    `;
    cursor = end;
  });
  markup += escapeHtml(text.slice(cursor));
  return markup;
}

function wireInlineBubbleToggles() {
  document.querySelectorAll(".inline-bubble-anchor").forEach((button) => {
    button.addEventListener("click", (event) => {
      const bubbleId = event.currentTarget.dataset.bubbleId;
      document.querySelectorAll(".inline-bubble-tip.is-open").forEach((tip) => {
        if (tip.dataset.bubbleId !== bubbleId) {
          tip.classList.remove("is-open");
        }
      });
      const target = document.querySelector(`.inline-bubble-tip[data-bubble-id="${bubbleId}"]`);
      if (target) {
        target.classList.toggle("is-open");
      }
      event.stopPropagation();
    });
  });
}

function renderPassages() {
  const container = document.getElementById("passage-list");
  const pageItems = getCurrentPageItems();
  container.innerHTML = "";
  updatePageIndicator();

  if (!pageItems.length) {
    container.innerHTML = `<p class="muted">There is no visible content in the current chapter yet.</p>`;
    return;
  }

  const page = document.createElement("article");
  page.className = "reading-page";
  page.innerHTML = `
    <header class="reading-page-header">
      <span>Chapter ${state.activeChapter}</span>
      <span>Page ${state.activePageIndex + 1}</span>
    </header>
  `;

  pageItems.forEach((passage, index) => {
    const paragraphIndex = passage.paragraph_index ?? passage._index + 1;
    const wrapper = document.createElement("article");
    wrapper.className = `reading-paragraph ${paragraphIndex === state.activeParagraphIndex ? "is-selected" : ""}`;
    wrapper.dataset.paragraphIndex = String(paragraphIndex);
    wrapper.innerHTML = `
      <span class="paragraph-marker">${paragraphIndex}</span>
      <div class="reading-paragraph-text">${createInlineBubbleMarkup(passage.text || "", passage.chunk_id)}</div>
    `;
    wrapper.addEventListener("click", () => selectPassage(passage, index, pageItems));
    page.appendChild(wrapper);
  });

  container.appendChild(page);
  wireInlineBubbleToggles();
}

function selectPassage(passage, index, passages) {
  state.activeParagraphIndex = passage.paragraph_index ?? passage._index + 1;
  state.activeChunkId = passage.chunk_id || null;
  updateProgressFromPassage(passage);
  buildSelectionFromPassage(passage, index, passages);
  renderSelectionPreview();
  renderReaderHeader();
  renderPassages();
  if (state.graphViewVisible) {
    refreshKnowledgeGraph().catch((error) => console.error(error));
  }
}

function setPage(pageIndex) {
  const pages = getCurrentPages();
  if (!pages.length) {
    state.activePageIndex = 0;
    renderPassages();
    return;
  }
  state.activePageIndex = Math.max(0, Math.min(pageIndex, pages.length - 1));
  const pageItems = getCurrentPageItems();
  const firstVisible = pageItems[0];
  if (firstVisible) {
    state.activeParagraphIndex = firstVisible.paragraph_index ?? firstVisible._index + 1;
    updateProgressFromPassage(firstVisible);
  }
  renderReaderHeader();
  renderPassages();
  fetchInlineBubbles().catch((error) => console.error(error));
}

async function fetchInlineBubbles() {
  if (!state.activeBook) {
    return;
  }
  const pageItems = getCurrentPageItems();
  if (!pageItems.length) {
    state.inlineBubblesByChunk = {};
    renderPassages();
    return;
  }
  try {
    const bubbles = await fetchJSON(`/api/books/${state.activeBook}/inline-bubbles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book_id: state.activeBook,
        current_chapter: state.activeChapter,
        visible_chunk_ids: pageItems.map((item) => item.chunk_id),
        persona_id: state.personaId,
        assistant_mode: state.assistantMode,
        character_name: state.activeCharacterName,
        max_bubbles: 3,
      }),
    });
    const map = {};
    bubbles.forEach((bubble) => {
      if (!map[bubble.chunk_id]) {
        map[bubble.chunk_id] = [];
      }
      map[bubble.chunk_id].push(bubble);
    });
    state.inlineBubblesByChunk = map;
    renderPassages();
  } catch (error) {
    console.error("Inline bubble generation failed", error);
  }
}

async function loadCharacterCandidates() {
  if (!state.activeBook) {
    state.characterCandidates = [];
    renderCharacterCandidates();
    return;
  }

  setButtonLoading("character-generate-btn", true, "Loading candidates...");
  try {
    state.characterCandidates = await fetchJSON(
      `/api/books/${state.activeBook}/characters?current_chapter=${state.activeChapter}&limit=12`
    );
    renderCharacterCandidates();
  } catch (error) {
    state.characterCandidates = [];
    renderCharacterCandidates();
    document.getElementById("character-profile-card").innerHTML = `<p class="muted">Failed to load character candidates: ${escapeHtml(
      error.message
    )}</p>`;
  } finally {
    setButtonLoading("character-generate-btn", false);
  }
}

async function generateCharacterProfile() {
  if (!state.activeBook) {
    return;
  }

  const typedName = document.getElementById("character-input").value.trim();
  const selectedName = document.getElementById("character-select").value.trim();
  const characterName = typedName || selectedName;
  if (!characterName) {
    document.getElementById("character-profile-card").innerHTML =
      `<p class="muted">Choose a candidate or enter a character name before building a character profile.</p>`;
    return;
  }

  state.activeCharacterName = characterName;
  renderAssistantStatus();
  setButtonLoading("character-generate-btn", true, "Building profile...");
  startPendingWorkflow("characterProfile", "building-profile");

  try {
    const profile = await fetchJSON(`/api/books/${state.activeBook}/characters/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book_id: state.activeBook,
        character_name: characterName,
        current_chapter: state.activeChapter,
      }),
    });
    state.activeCharacterProfile = profile;
    document.getElementById("character-input").value = profile.character_name;
    renderCharacterProfile();
    renderAssistantStatus();
    if (state.assistantMode === "character") {
      await fetchInlineBubbles();
    }
    finishPendingWorkflow("done", "Character profile ready", "The character profile has been built from the currently visible reading scope.");
  } catch (error) {
    document.getElementById("character-profile-card").innerHTML = `<p class="muted">Failed to build character profile: ${escapeHtml(
      error.message
    )}</p>`;
    setPendingState(false);
  } finally {
    if (state.pendingWorkflow) {
      releasePendingState();
    }
    setButtonLoading("character-generate-btn", false);
  }
}

async function setActiveChapter(chapter) {
  state.activeChapter = Number(chapter);
  state.activePageIndex = 0;
  state.chapterEnteredAt = Date.now();
  state.activeChunkId = null;
  state.activeCharacterProfile = null;
  resetSelection();

  const passages = getCurrentPassages();
  const first = passages[0] || null;
  state.activeParagraphIndex = first ? first.paragraph_index ?? 1 : null;
  state.readingProgress = {
    book_id: state.activeBook || "",
    chapter_id: state.activeChapter,
    section_id: `sec-${state.activeChapter}`,
    paragraph_id: first ? String(first.paragraph_index ?? 1) : "",
    token_offset: first?.text ? first.text.length : 0,
    scroll_offset: 0,
    dwell_seconds: 0,
    updated_at: new Date().toISOString(),
  };

  renderChapterNav();
  renderChapterSelects();
  renderReaderHeader();
  renderSelectionPreview();
  renderPassages();
  renderCharacterProfile();
  await loadCharacterCandidates();
  await fetchInlineBubbles();
  if (state.graphViewVisible) {
    await refreshKnowledgeGraph();
  }
}

async function loadPersonas() {
  state.personas = await fetchJSON("/api/personas");
  const select = document.getElementById("persona-select");
  select.innerHTML = state.personas
    .map((persona) => `<option value="${escapeHtml(persona.persona_id)}">${escapeHtml(persona.name)}</option>`)
    .join("");

  const preferred =
    state.personas.find((persona) => persona.persona_id === state.personaId) ||
    state.personas.find((persona) => persona.persona_id !== "neutral") ||
    state.personas[0] ||
    null;

  if (preferred) {
    state.personaId = preferred.persona_id;
    select.value = state.personaId;
  }

  select.addEventListener("change", async (event) => {
    state.personaId = event.target.value;
    renderPersonaDetails();
    renderAssistantStatus();
    if (state.assistantMode === "persona") {
      await fetchInlineBubbles();
    }
  });

  renderPersonaDetails();
}

async function loadBooks() {
  state.books = await fetchJSON("/api/books");
  renderBooks();
}

async function openBook(bookId) {
  state.activeBook = bookId;
  state.activeBookDetail = await fetchJSON(`/api/books/${bookId}`);
  state.personaConversation = [];
  state.characterConversation = [];
  state.activeCharacterName = "";
  state.activeCharacterProfile = null;
  state.graphViewData = null;
  state.graphViewError = "";
  renderBooks();
  renderChatHistory();
  renderGraphPanel();
  await setActiveChapter(getFirstReadableChapter());
}

async function uploadBook(event) {
  event.preventDefault();
  const input = document.getElementById("file-input");
  if (!input.files[0]) {
    return;
  }

  setPendingState(true, "starting-upload", "Starting upload", "Creating an upload job and waiting for the pipeline to begin.");
  try {
    const payload = new FormData();
    payload.append("file", input.files[0]);
    const job = await fetchJSON("/api/upload-jobs", {
      method: "POST",
      body: payload,
    });
    applyUploadJobState(job);
    const uploaded = await waitForUploadJob(job.job_id);
    await loadBooks();
    await openBook(uploaded.book_id);
    input.value = "";
    finishPendingWorkflow(
      "done",
      "Temporal graph ready",
      `${uploaded.book_title || uploaded.title} has been parsed and its temporal graph is ready for reading.`
    );
  } catch (error) {
    pushConversation("assistant", `Import failed: ${error.message}`);
    renderChatHistory();
    setPendingState(false);
  } finally {
    if (state.pendingWorkflow) {
      releasePendingState();
    }
  }
}

function renderComposerQuestion(text = "") {
  document.getElementById("question-input").value = text;
}

async function askAssistant() {
  if (!state.activeBook) {
    return;
  }
  const question = document.getElementById("question-input").value.trim();
  if (!question) {
    return;
  }

  const history = currentConversation().slice(-8);
  pushConversation("user", question);
  renderChatHistory();
  renderComposerQuestion("");
  setButtonLoading("ask-btn", true, "Generating answer...");
  startPendingWorkflow(
    state.assistantMode === "persona" ? "personaQa" : "characterQa",
    state.assistantMode === "persona" ? "persona-answering" : "character-answering"
  );

  try {
    let answer = "";
    if (state.assistantMode === "persona") {
      const response = await fetchJSON("/api/qa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_id: state.activeBook,
          question,
          highlight_text: state.selectionContext.selected_text,
          current_chapter: state.activeChapter,
          persona_id: state.personaId,
          conversation_history: history,
        }),
      });
      answer = response.answer;
    } else {
      if (!state.activeCharacterName) {
        throw new Error("Choose or build a character profile before asking the character agent.");
      }
      const response = await fetchJSON(`/api/books/${state.activeBook}/characters/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_id: state.activeBook,
          character_name: state.activeCharacterName,
          question,
          current_chapter: state.activeChapter,
          conversation_history: history,
        }),
      });
      answer = response.answer;
      state.activeCharacterProfile = response.profile;
      renderCharacterProfile();
    }
    pushConversation("assistant", answer);
    renderChatHistory();
    finishPendingWorkflow(
      "done",
      state.assistantMode === "persona" ? "Literary answer ready" : "Character answer ready",
      state.assistantMode === "persona"
        ? "The literary agent answer has been generated from visible book context, persona RAG, and prompt policy."
        : "The character agent answer has been generated from visible book context and character profile grounding."
    );
  } catch (error) {
    pushConversation("assistant", `Question failed: ${error.message}`);
    renderChatHistory();
    setPendingState(false);
  } finally {
    setButtonLoading("ask-btn", false);
    if (state.pendingWorkflow) {
      releasePendingState();
    }
  }
}

async function summarizeChapter() {
  if (!state.activeBook) {
    return;
  }

  setButtonLoading("summary-btn", true, "Summarizing...");
  startPendingWorkflow("chapterSummary", "chapter-summary");
  try {
    const response = await fetchJSON("/api/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book_id: state.activeBook,
        current_chapter: state.activeChapter,
        persona_id: state.personaId,
      }),
    });
    state.assistantMode = "persona";
    renderAssistantMode();
    pushConversation("assistant", response.summary);
    renderChatHistory();
    finishPendingWorkflow("done", "Chapter summary ready", "The current chapter summary has been generated from visible chapter context and graph state.");
  } catch (error) {
    pushConversation("assistant", `Summary failed: ${error.message}`);
    renderChatHistory();
    setPendingState(false);
  } finally {
    setButtonLoading("summary-btn", false);
    if (state.pendingWorkflow) {
      releasePendingState();
    }
  }
}

function clearConversation() {
  if (state.assistantMode === "persona") {
    state.personaConversation = [];
  } else {
    state.characterConversation = [];
  }
  renderChatHistory();
}

function setAssistantMode(mode) {
  state.assistantMode = mode;
  renderAssistantMode();
  fetchInlineBubbles().catch((error) => console.error(error));
}

function wireEvents() {
  document.getElementById("upload-form").addEventListener("submit", uploadBook);
  document.getElementById("ask-btn").addEventListener("click", askAssistant);
  document.getElementById("summary-btn").addEventListener("click", summarizeChapter);
  document.getElementById("graph-toggle-btn").addEventListener("click", () => {
    toggleKnowledgeGraph().catch((error) => console.error(error));
  });
  document.getElementById("graph-refresh-btn").addEventListener("click", () => {
    refreshKnowledgeGraph().catch((error) => console.error(error));
  });
  document.getElementById("graph-scope-chapter-btn").addEventListener("click", () => {
    setKnowledgeGraphScope("chapter").catch((error) => console.error(error));
  });
  document.getElementById("graph-scope-book-btn").addEventListener("click", () => {
    setKnowledgeGraphScope("book").catch((error) => console.error(error));
  });
  document.getElementById("clear-chat-btn").addEventListener("click", clearConversation);
  document.getElementById("persona-mode-btn").addEventListener("click", () => setAssistantMode("persona"));
  document.getElementById("character-mode-btn").addEventListener("click", () => setAssistantMode("character"));
  document.getElementById("character-select").addEventListener("change", (event) => {
    state.activeCharacterName = event.target.value.trim();
    document.getElementById("character-input").value = state.activeCharacterName;
    renderAssistantStatus();
  });
  document.getElementById("character-generate-btn").addEventListener("click", generateCharacterProfile);
  document.getElementById("chapter-select").addEventListener("change", async (event) => {
    await setActiveChapter(Number(event.target.value));
  });
  document.getElementById("paragraph-jump").addEventListener("change", (event) => {
    const targetValue = event.target.value;
    const allPassages = getCurrentPassages();
    const passage = allPassages.find((item, index) => String(item.paragraph_index ?? index + 1) === targetValue);
    if (!passage) {
      return;
    }
    const pageIndex = getCurrentPages().findIndex((page) =>
      page.some((item) => String(item.paragraph_index ?? item._index + 1) === targetValue)
    );
    if (pageIndex >= 0) {
      state.activePageIndex = pageIndex;
    }
    const pageItems = getCurrentPageItems();
    const indexInPage = pageItems.findIndex((item) => item.chunk_id === passage.chunk_id);
    selectPassage(passage, Math.max(0, indexInPage), pageItems.length ? pageItems : allPassages);
  });
  document.getElementById("prev-page-btn").addEventListener("click", () => setPage(state.activePageIndex - 1));
  document.getElementById("next-page-btn").addEventListener("click", () => setPage(state.activePageIndex + 1));
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".inline-bubble")) {
      document.querySelectorAll(".inline-bubble-tip.is-open").forEach((tip) => tip.classList.remove("is-open"));
    }
  });
}

async function bootstrap() {
  wireEvents();
  renderPendingWorkflow();
  renderReaderHeader();
  renderSelectionPreview();
  renderCharacterProfile();
  renderAssistantMode();
  renderGraphPanel();
  await loadPersonas();
  await loadBooks();
  if (state.books[0]) {
    await openBook(state.books[0].book_id);
  }
}

bootstrap().catch((error) => {
  console.error(error);
});



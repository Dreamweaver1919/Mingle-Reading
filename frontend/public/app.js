const state = {
  books: [],
  personas: [],
  activeBook: null,
  activeBookDetail: null,
  activeChapter: 1,
  activeParagraphIndex: null,
  activeChunkId: null,
  personaId: "neutral",
  sessionId: `sess_${Date.now()}`,
  requestCounter: 0,
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

const bubbleTemplates = [
  {
    title: "节奏提示",
    body: "当停留时间更长时，这里可以接 Bubble Trigger Engine，主动提示关键句、情绪转折或隐含线索。",
  },
  {
    title: "防剧透护栏",
    body: "后续可根据 reading_progress.chapter_id 控制提示只覆盖当前章节与已读范围。",
  },
  {
    title: "角色视角",
    body: "这里可挂接 character / lead_reader 两类 agent，为同一段落给出不同 persona 的主动观察。",
  },
];

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function nextRequestId(prefix) {
  state.requestCounter += 1;
  return `${prefix}_${state.requestCounter}`;
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function previewText(text, fallback = "暂无内容") {
  return text && text.trim() ? text : fallback;
}

function setOutput(mode, content) {
  document.getElementById("output-mode").textContent = mode;
  document.getElementById("output-box").textContent = content;
}

function getPersonaById(personaId) {
  return state.personas.find((persona) => persona.persona_id === personaId) || state.personas[0] || null;
}

function renderBubblePlaceholders() {
  const container = document.getElementById("bubble-list");
  container.innerHTML = "";
  bubbleTemplates.forEach((bubble) => {
    const card = document.createElement("article");
    card.className = "bubble-card";
    card.innerHTML = `
      <p class="bubble-title">${bubble.title}</p>
      <p class="muted">${bubble.body}</p>
    `;
    container.appendChild(card);
  });
}

function renderPayloadPreview() {
  document.getElementById("reading-progress-box").textContent = formatJson(state.readingProgress);
  document.getElementById("selection-context-box").textContent = formatJson(state.selectionContext);
}

function renderPersonaDetails() {
  const persona = getPersonaById(state.personaId);
  if (!persona) {
    return;
  }

  document.getElementById("persona-type-badge").textContent = persona.source_type;
  document.getElementById("persona-name").textContent = persona.name;
  document.getElementById("persona-citation").textContent = persona.citation;

  const traits = document.getElementById("persona-traits");
  traits.innerHTML = "";
  [...persona.style_traits, ...persona.reasoning_style].slice(0, 5).forEach((item) => {
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = item;
    traits.appendChild(pill);
  });

  const scaffold = document.getElementById("persona-scaffold");
  scaffold.innerHTML = "";
  (persona.prompt_scaffold || []).slice(0, 3).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    scaffold.appendChild(li);
  });
  if (!scaffold.children.length) {
    const li = document.createElement("li");
    li.textContent = "当前 persona 没有额外 scaffold，按默认阅读者风格输出。";
    scaffold.appendChild(li);
  }
}

function renderBooks() {
  const list = document.getElementById("book-list");
  list.innerHTML = "";
  document.getElementById("book-count").textContent = `${state.books.length} 本`;

  state.books.forEach((book) => {
    const item = document.createElement("li");
    item.className = "book-item";

    const button = document.createElement("button");
    button.type = "button";
    button.className = `book-button ${state.activeBook === book.book_id ? "is-active" : ""}`;
    button.innerHTML = `
      <span class="book-title">${book.title}</span>
      <span class="book-meta">${book.book_id}</span>
    `;
    button.addEventListener("click", () => openBook(book.book_id));

    item.appendChild(button);
    list.appendChild(item);
  });
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

function updateHeroStats() {
  document.getElementById("hero-chapter").textContent = state.activeBook ? `第 ${state.activeChapter} 章` : "-";
  document.getElementById("hero-paragraph").textContent =
    state.activeParagraphIndex === null ? "-" : `P${state.activeParagraphIndex}`;
  document.getElementById("hero-dwell").textContent = `${state.readingProgress.dwell_seconds || 0}s`;
}

function buildSelectionFromPassage(passage, index, passages) {
  const prev = passages[index - 1];
  const next = passages[index + 1];
  state.selectionContext = {
    book_id: state.activeBook || "",
    selection_id: `sel_${passage.chunk_id || index + 1}`,
    selected_text: passage.text,
    left_context: prev ? prev.text : "",
    right_context: next ? next.text : "",
    anchor: {
      chapter_id: state.activeChapter,
      section_id: `sec-${state.activeChapter}`,
      paragraph_id: String(passage.paragraph_index ?? index + 1),
    },
  };
}

function updateProgressFromSelection(passage) {
  const scrollOffset = state.activeBookDetail
    ? Number((state.activeChapter / Math.max(state.activeBookDetail.chapter_count, 1)).toFixed(2))
    : 0;

  state.readingProgress = {
    book_id: state.activeBook || "",
    chapter_id: state.activeChapter,
    section_id: `sec-${state.activeChapter}`,
    paragraph_id: String(passage.paragraph_index ?? ""),
    token_offset: passage.text ? passage.text.length : 0,
    scroll_offset: scrollOffset,
    dwell_seconds: Math.max(1, Math.floor((Date.now() - state.chapterEnteredAt) / 1000)),
    updated_at: new Date().toISOString(),
  };
}

function updateSelectionPanel() {
  document.getElementById("highlight-preview").textContent = previewText(
    state.selectionContext.selected_text,
    "点击中间段落后，这里会生成选中文本和左右文上下文预览。"
  );
  document.getElementById("left-context").textContent = previewText(
    state.selectionContext.left_context,
    "当前选中内容前面暂无段落。"
  );
  document.getElementById("right-context").textContent = previewText(
    state.selectionContext.right_context,
    "当前选中内容后面暂无段落。"
  );
}

function selectPassage(passage, index, passages) {
  state.activeParagraphIndex = passage.paragraph_index ?? index + 1;
  state.activeChunkId = passage.chunk_id || null;
  updateProgressFromSelection(passage);
  buildSelectionFromPassage(passage, index, passages);
  updateSelectionPanel();
  updateHeroStats();
  renderPayloadPreview();
  renderPassages();
}

function renderChapterNav() {
  const container = document.getElementById("chapter-nav");
  container.innerHTML = "";

  if (!state.activeBookDetail) {
    container.innerHTML = '<p class="muted">书籍载入后会显示章节目录。</p>';
    return;
  }

  for (let chapter = 1; chapter <= state.activeBookDetail.chapter_count; chapter += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chapter-button ${chapter === state.activeChapter ? "is-active" : ""}`;
    button.textContent = `第 ${chapter} 章`;
    button.addEventListener("click", () => setActiveChapter(chapter));
    container.appendChild(button);
  }

  document.getElementById("toc-progress").textContent = `已读至第 ${state.activeChapter} 章`;
}

function renderChapterSelects() {
  const chapterSelect = document.getElementById("chapter-select");
  const paragraphSelect = document.getElementById("paragraph-jump");
  const passages = getCurrentPassages();

  chapterSelect.innerHTML = "";
  paragraphSelect.innerHTML = "";

  if (!state.activeBookDetail) {
    return;
  }

  for (let chapter = 1; chapter <= state.activeBookDetail.chapter_count; chapter += 1) {
    const option = document.createElement("option");
    option.value = String(chapter);
    option.textContent = `第 ${chapter} 章`;
    chapterSelect.appendChild(option);
  }
  chapterSelect.value = String(state.activeChapter);

  passages.forEach((passage, index) => {
    const option = document.createElement("option");
    const paragraphIndex = passage.paragraph_index ?? index + 1;
    option.value = String(paragraphIndex);
    option.textContent = `段落 ${paragraphIndex}`;
    paragraphSelect.appendChild(option);
  });

  if (state.activeParagraphIndex !== null) {
    paragraphSelect.value = String(state.activeParagraphIndex);
  } else if (passages[0]) {
    paragraphSelect.value = String(passages[0].paragraph_index ?? 1);
  }
}

function renderPassages() {
  const container = document.getElementById("passage-list");
  const passages = getCurrentPassages();
  container.innerHTML = "";

  if (!passages.length) {
    container.innerHTML = '<p class="muted">当前章节还没有可显示的段落。</p>';
    return;
  }

  passages.forEach((passage, index) => {
    const paragraphIndex = passage.paragraph_index ?? index + 1;
    const article = document.createElement("article");
    article.className = `passage ${paragraphIndex === state.activeParagraphIndex ? "selected" : ""}`;
    article.innerHTML = `
      <div class="passage-meta">
        <span>段落 ${paragraphIndex}</span>
        <span>${passage.chunk_id || "chunk"}</span>
      </div>
      <p>${passage.text}</p>
    `;
    article.addEventListener("click", () => selectPassage(passage, index, passages));
    container.appendChild(article);
  });
}

function renderReaderHeader() {
  if (!state.activeBookDetail) {
    document.getElementById("book-title").textContent = "请选择一本书开始阅读";
    document.getElementById("book-subtitle").textContent =
      "页面会跟踪章节、段落与滚动位置，并构造对齐架构文档的 `reading_progress`。";
    document.getElementById("progress-text").textContent = "尚未载入书籍。";
    updateHeroStats();
    return;
  }

  document.getElementById("book-title").textContent = state.activeBookDetail.title;
  document.getElementById("book-subtitle").textContent =
    `book_id: ${state.activeBookDetail.book_id}，共 ${state.activeBookDetail.chapter_count} 章。`;
  document.getElementById("progress-text").textContent =
    `当前位于第 ${state.readingProgress.chapter_id} 章 / 段落 ${state.readingProgress.paragraph_id || "-"}，scroll_offset=${state.readingProgress.scroll_offset}`;
  updateHeroStats();
}

function setActiveChapter(chapter) {
  state.activeChapter = Number(chapter);
  state.chapterEnteredAt = Date.now();
  state.activeParagraphIndex = null;
  state.activeChunkId = null;
  const passages = getCurrentPassages();

  state.readingProgress = {
    book_id: state.activeBook || "",
    chapter_id: state.activeChapter,
    section_id: `sec-${state.activeChapter}`,
    paragraph_id: passages[0] ? String(passages[0].paragraph_index ?? 1) : "",
    token_offset: 0,
    scroll_offset: Number((state.activeChapter / Math.max(state.activeBookDetail?.chapter_count || 1, 1)).toFixed(2)),
    dwell_seconds: 0,
    updated_at: new Date().toISOString(),
  };

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

  renderChapterNav();
  renderChapterSelects();
  renderReaderHeader();
  renderPassages();
  updateSelectionPanel();
  renderPayloadPreview();
}

async function loadPersonas() {
  state.personas = await fetchJSON("/api/personas");
  const select = document.getElementById("persona-select");
  select.innerHTML = state.personas
    .map((persona) => `<option value="${persona.persona_id}">${persona.name}</option>`)
    .join("");

  select.value = state.personaId;
  select.addEventListener("change", (event) => {
    state.personaId = event.target.value;
    renderPersonaDetails();
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
  state.chapterEnteredAt = Date.now();
  renderBooks();
  setActiveChapter(1);
}

async function uploadBook(event) {
  event.preventDefault();
  const input = document.getElementById("file-input");
  if (!input.files[0]) {
    setOutput("error", "请选择一个 TXT 文件后再上传。");
    return;
  }

  const payload = new FormData();
  payload.append("file", input.files[0]);
  const uploaded = await fetchJSON("/api/upload", {
    method: "POST",
    body: payload,
  });

  await loadBooks();
  await openBook(uploaded.book_id);
  setOutput(
    "upload",
    `已导入《${uploaded.title}》\nbook_id: ${uploaded.book_id}\n章节数: ${uploaded.chapter_count}\n段落块数: ${uploaded.chunk_count}`
  );
  input.value = "";
}

function buildAgentRequest(mode, questionText = "") {
  return {
    request_id: nextRequestId("req"),
    session_id: state.sessionId,
    user_id: "local-user",
    mode,
    agent_type: "lead_reader",
    agent_id: state.personaId,
    book_id: state.activeBook,
    question: questionText,
    selection_context: state.selectionContext,
    reading_progress: state.readingProgress,
    preferences: {
      language: "zh-CN",
      verbosity: "short",
      spoiler_guard: true,
    },
  };
}

async function askQuestion() {
  if (!state.activeBook) {
    setOutput("error", "请先打开一本书。");
    return;
  }

  const question = document.getElementById("question-input").value.trim();
  if (!question) {
    setOutput("error", "请输入问题后再发送。");
    return;
  }

  const agentRequest = buildAgentRequest("chat", question);
  const response = await fetchJSON("/api/qa", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      book_id: agentRequest.book_id,
      question: agentRequest.question,
      highlight_text: agentRequest.selection_context.selected_text,
      current_chapter: agentRequest.reading_progress.chapter_id,
      persona_id: agentRequest.agent_id,
    }),
  });

  const contextSummary = (response.contexts || [])
    .map(
      (ctx) =>
        `- c${ctx.chapter_index} / p${ctx.paragraph_index} / score=${ctx.score}\n  ${ctx.text.slice(0, 90)}`
    )
    .join("\n");

  setOutput(
    "chat",
    [
      "[agent_request preview]",
      formatJson(agentRequest),
      "",
      "[answer]",
      response.answer,
      "",
      `[safe] ${response.safe}`,
      `[reason] ${response.reason}`,
      "",
      "[contexts]",
      contextSummary || "无检索上下文返回。",
    ].join("\n")
  );
}

async function summarizeChapter() {
  if (!state.activeBook) {
    setOutput("error", "请先打开一本书。");
    return;
  }

  const agentRequest = buildAgentRequest("summary");
  const response = await fetchJSON("/api/summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      book_id: agentRequest.book_id,
      current_chapter: agentRequest.reading_progress.chapter_id,
      persona_id: agentRequest.agent_id,
    }),
  });

  setOutput(
    "summary",
    [
      "[agent_request preview]",
      formatJson(agentRequest),
      "",
      "[summary]",
      response.summary,
      "",
      `[chapter_id] ${response.chapter_id}`,
      `[persona_id] ${response.persona_id}`,
    ].join("\n")
  );
}

function wireEvents() {
  document.getElementById("upload-form").addEventListener("submit", uploadBook);
  document.getElementById("ask-btn").addEventListener("click", askQuestion);
  document.getElementById("summary-btn").addEventListener("click", summarizeChapter);
  document.getElementById("chapter-select").addEventListener("change", (event) => {
    setActiveChapter(Number(event.target.value));
  });
  document.getElementById("paragraph-jump").addEventListener("change", (event) => {
    const passages = getCurrentPassages();
    const target = passages.find(
      (passage, index) => String(passage.paragraph_index ?? index + 1) === event.target.value
    );
    if (target) {
      const index = passages.indexOf(target);
      selectPassage(target, index, passages);
    }
  });
}

async function bootstrap() {
  wireEvents();
  renderBubblePlaceholders();
  renderPayloadPreview();
  updateSelectionPanel();
  renderReaderHeader();

  await loadPersonas();
  await loadBooks();

  if (state.books[0]) {
    await openBook(state.books[0].book_id);
  }
}

bootstrap().catch((error) => {
  setOutput("error", String(error));
});

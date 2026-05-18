const CHARS_PER_PAGE = 1150;
const REQUEST_TIMEOUT_MS = 300000;
const WORKFLOW_TICK_MS = 900;

const PENDING_WORKFLOWS = {
  idle: {
    title: "Idle",
    description: "等待用户发起上传、问答或总结请求。",
    steps: [],
  },
  uploadGraph: {
    title: "Graphiti Temporal Graph Build",
    description: "正在把上传文本转换成 Graphiti 风格的时序知识图谱基座。",
    steps: [
      { name: "Extract source text", copy: "读取 TXT / PDF / EPUB，并提取后续建图所需的正文。" },
      { name: "Segment chapters", copy: "按章节和段落切分文本，建立稳定的阅读边界。" },
      { name: "Construct episodes", copy: "把段落转换为 canonical episodes，并串起 narrative order。" },
      { name: "Resolve entities", copy: "结合已有图节点和上下文，做 LLM-assisted entity resolution。" },
      { name: "Resolve facts", copy: "抽取人物、地点、关系和状态事实，并做 temporal invalidation。" },
      { name: "Build communities", copy: "汇总 chapter timeline、community 和 saga 结构。" },
      { name: "Build sagas", copy: "把跨章节的叙事主线整理成 saga 级结构。" },
      { name: "Assemble chapter timeline", copy: "把 episode、entity 和 relation 汇总成章节时间线。" },
      { name: "Serialize graph payload", copy: "把内存中的图节点、边和元数据序列化为可落盘格式。" },
      { name: "Persist book record", copy: "先写入 book record，固定章节、段落和阅读视图数据。" },
      { name: "Persist graph snapshot", copy: "写入 temporal graph 快照、relations、communities 和 sagas。" },
      { name: "Finalize graph metadata", copy: "收尾图统计、storage metadata 和前端可读索引。" },
    ],
  },
  personaQa: {
    title: "Persona Answering",
    description: "正在组合书本上下文、名家 persona RAG 和防剧透约束。",
    steps: [
      { name: "Read current scope", copy: "定位当前章节、高亮和可见上下文。" },
      { name: "Retrieve graph context", copy: "从 temporal graph 检索当前问题相关的已读事实。" },
      { name: "Retrieve persona context", copy: "召回名家资料片段和风格证据。" },
      { name: "Apply spoiler guard", copy: "根据当前进度过滤未来信息，只保留可见范围。" },
      { name: "Generate answer", copy: "组织成完整名家回答并写回对话区。" },
    ],
  },
  characterQa: {
    title: "Character Companion Answering",
    description: "正在让书中角色在当前已读边界内进行陪读回应。",
    steps: [
      { name: "Read visible scope", copy: "定位当前章节和用户高亮对应的可见文本。" },
      { name: "Resolve character memory", copy: "检索角色在当前进度前已经出现的事件和关系。" },
      { name: "Apply spoiler guard", copy: "过滤角色未来命运和后文未揭示信息。" },
      { name: "Generate answer", copy: "以角色身份输出连续陪读回答。" },
    ],
  },
  chapterSummary: {
    title: "Chapter Summary",
    description: "正在根据当前已读内容生成阶段性总结。",
    steps: [
      { name: "Collect chapter episodes", copy: "收集当前章节已读段落和相邻证据。" },
      { name: "Read graph state", copy: "整理人物、关系和主题在本章的局部演化。" },
      { name: "Apply spoiler guard", copy: "阻断未来章节信息，只总结当前可见范围。" },
      { name: "Generate summary", copy: "输出阶段总结并写入对话记录。" },
    ],
  },
  characterProfile: {
    title: "Character Profile Build",
    description: "正在根据当前已读文本生成角色画像。",
    steps: [
      { name: "Find character evidence", copy: "在当前已读范围内定位角色出现的证据段落。" },
      { name: "Assemble relation view", copy: "汇总该角色可见的人物关系和张力。" },
      { name: "Generate profile", copy: "生成用于前端可视化的角色卡片。" },
    ],
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
  sessionId: `sess_${Date.now()}`,
  requestCounter: 0,
  pendingWorkflow: null,
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

let pendingWorkflowTimer = null;

async function fetchJSON(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(url, { ...options, signal: options.signal || controller.signal });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`请求等待超过 ${REQUEST_TIMEOUT_MS / 1000}s。`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }

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
}

function clearPendingWorkflowTimer() {
  if (pendingWorkflowTimer) {
    window.clearInterval(pendingWorkflowTimer);
    pendingWorkflowTimer = null;
  }
}

function renderPendingWorkflow() {
  const indicator = document.getElementById("pending-indicator");
  const pendingLabel = document.getElementById("pending-label");
  const pendingTitle = document.getElementById("pending-title");
  const pendingDescription = document.getElementById("pending-description");
  const pendingBar = document.getElementById("pending-bar");
  const pendingPercent = document.getElementById("pending-percent");
  const pendingStepCaption = document.getElementById("pending-step-caption");

  if (!indicator || !pendingLabel || !pendingTitle || !pendingDescription || !pendingBar || !pendingPercent || !pendingStepCaption) {
    return;
  }

  const workflow = state.pendingWorkflow;
  if (!workflow) {
    pendingLabel.textContent = "idle";
    pendingTitle.textContent = PENDING_WORKFLOWS.idle.title;
    pendingDescription.textContent = PENDING_WORKFLOWS.idle.description;
    pendingBar.style.width = "0%";
    pendingPercent.textContent = "0%";
    pendingStepCaption.textContent = "当前没有运行中的流程。";
    indicator.classList.remove("is-active", "is-indeterminate");
    return;
  }

  indicator.classList.add("is-active");
  indicator.classList.toggle("is-indeterminate", workflow.indeterminate === true);
  pendingLabel.textContent = workflow.label;
  pendingTitle.textContent = workflow.title;
  pendingDescription.textContent = workflow.description;
  pendingBar.style.width = workflow.indeterminate ? "32%" : `${workflow.percent}%`;
  pendingPercent.textContent = `${workflow.percent}%`;
  pendingStepCaption.textContent = workflow.currentStep?.copy || "正在等待下一步状态。";
}

function setPendingState(active, label = "idle") {
  if (!active) {
    clearPendingWorkflowTimer();
    state.pendingWorkflow = null;
    renderPendingWorkflow();
    return;
  }
  state.pendingWorkflow = {
    label,
    title: "Processing",
    description: "正在处理请求。",
    steps: [],
    currentIndex: -1,
    currentStep: null,
    percent: 12,
    indeterminate: true,
  };
  renderPendingWorkflow();
}

function startPendingWorkflow(workflowKey, label = "running") {
  clearPendingWorkflowTimer();
  const template = PENDING_WORKFLOWS[workflowKey] || PENDING_WORKFLOWS.idle;
  const steps = template.steps || [];
  const totalSteps = steps.length || 1;
  const basePercent = steps.length ? Math.max(8, Math.round(100 / (totalSteps + 1))) : 18;
  state.pendingWorkflow = {
    key: workflowKey,
    label,
    title: template.title,
    description: template.description,
    steps,
    currentIndex: 0,
    currentStep: steps[0] || null,
    percent: steps.length ? basePercent : 18,
    indeterminate: false,
  };
  renderPendingWorkflow();

  if (!steps.length) {
    return;
  }

  pendingWorkflowTimer = window.setInterval(() => {
    if (!state.pendingWorkflow || state.pendingWorkflow.key !== workflowKey) {
      clearPendingWorkflowTimer();
      return;
    }
    const nextIndex = Math.min(state.pendingWorkflow.currentIndex + 1, totalSteps - 1);
    state.pendingWorkflow.currentIndex = nextIndex;
    state.pendingWorkflow.currentStep = steps[nextIndex];
    state.pendingWorkflow.percent = Math.min(92, basePercent + nextIndex * Math.round(84 / totalSteps));
    renderPendingWorkflow();
    if (nextIndex >= totalSteps - 1) {
      clearPendingWorkflowTimer();
    }
  }, WORKFLOW_TICK_MS);
}

function finishPendingWorkflow(label = "done", title = "Completed", description = "流程已经完成。") {
  clearPendingWorkflowTimer();
  if (!state.pendingWorkflow) {
    return;
  }
  const lastIndex = Math.max(0, state.pendingWorkflow.steps.length - 1);
  state.pendingWorkflow = {
    ...state.pendingWorkflow,
    label,
    title,
    description,
    currentIndex: lastIndex,
    currentStep: state.pendingWorkflow.steps[lastIndex] || null,
    percent: 100,
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

function applyUploadJobState(job) {
  const processed = job.processed_snippets || 0;
  const total = job.total_snippets || 0;
  const snippetProgress = total ? `已处理文段 ${processed}/${total}` : "正在准备文段统计";
  const currentSnippet = job.current_snippet_id
    ? `当前文段 ${job.current_snippet_id}（chapter ${job.current_chapter_index || "-"} / paragraph ${job.current_paragraph_index || "-"}）`
    : "当前还没有锁定到具体文段";
  state.pendingWorkflow = {
    key: "uploadGraph",
    label: job.status,
    title: job.title || "Temporal graph build",
    description: job.message || "",
    percent: job.percent || 0,
    indeterminate: false,
    currentIndex: 0,
    currentStep: {
      name: job.stage || "running",
      copy: `${snippetProgress}。${currentSnippet}。`,
    },
    steps: [],
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
      throw new Error(job.error || job.message || "upload job failed");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
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

function nextRequestId(prefix) {
  state.requestCounter += 1;
  return `${prefix}_${state.requestCounter}`;
}

function getPersonaById(personaId) {
  return state.personas.find((persona) => persona.persona_id === personaId) || state.personas[0] || null;
}

function previewText(text, fallback = "还没有选中的文本") {
  return text && text.trim() ? text.trim() : fallback;
}

function getCurrentPassages() {
  if (!state.activeBookDetail) {
    return [];
  }
  return state.activeBookDetail.chapters[String(state.activeChapter)] || state.activeBookDetail.chapters[state.activeChapter] || [];
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
  let current = [];
  let size = 0;
  passages.forEach((passage, index) => {
    const nextSize = (passage.text || "").length + 80;
    if (current.length && size + nextSize > CHARS_PER_PAGE) {
      pages.push(current);
      current = [];
      size = 0;
    }
    current.push({ ...passage, _index: index });
    size += nextSize;
  });
  if (current.length) {
    pages.push(current);
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

function updateProgressFromSelection(passage) {
  const pages = getCurrentPages();
  const scrollOffset = pages.length ? Number(((state.activePageIndex + 1) / pages.length).toFixed(2)) : 0;
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
  [...persona.style_traits, ...persona.reasoning_style].slice(0, 6).forEach((item) => {
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = item;
    traits.appendChild(pill);
  });
}

function renderCharacterCandidates() {
  const select = document.getElementById("character-select");
  select.innerHTML = "";
  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = state.characterCandidates.length ? "请选择角色候选" : "暂无角色候选";
  select.appendChild(emptyOption);

  state.characterCandidates.forEach((candidate) => {
    const option = document.createElement("option");
    option.value = candidate.character_name;
    option.textContent = `${candidate.character_name} · ${candidate.mention_count} 次`;
    select.appendChild(option);
  });

  if (state.activeCharacterName) {
    select.value = state.activeCharacterName;
  }
}

function renderCharacterProfile() {
  const container = document.getElementById("character-profile-card");
  container.innerHTML = "";
  if (!state.activeCharacterProfile) {
    container.innerHTML = '<p class="muted">生成角色画像后，这里会展示当前已读范围内的角色摘要、张力和关系。</p>';
    return;
  }

  const profile = state.activeCharacterProfile;
  const traitRow = document.createElement("div");
  traitRow.className = "pill-row";
  (profile.core_traits || []).forEach((trait) => {
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = trait;
    traitRow.appendChild(pill);
  });

  const relationList = document.createElement("ul");
  relationList.className = "plain-list relationship-list";
  (profile.relationships || []).forEach((relation) => {
    const li = document.createElement("li");
    li.textContent = `${relation.target}：${relation.description}`;
    relationList.appendChild(li);
  });

  container.innerHTML = `
    <h4 class="character-name">${profile.character_name}</h4>
    <p class="muted">${profile.summary}</p>
    <p class="label">核心张力</p>
    <p class="signature-tension">${profile.signature_tension || "当前已读范围内还没有足够的角色冲突描述。"}</p>
    <p class="label">当前可见范围</p>
    <p class="muted">${profile.current_scope}</p>
    <p class="label">模型</p>
    <p class="muted">${profile.model_name}</p>
  `;
  container.appendChild(traitRow);
  if (relationList.children.length) {
    const heading = document.createElement("p");
    heading.className = "label";
    heading.textContent = "人物关系";
    container.appendChild(heading);
    container.appendChild(relationList);
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

function renderReaderHeader() {
  if (!state.activeBookDetail) {
    document.getElementById("book-title").textContent = "选择一本书开始阅读";
    document.getElementById("book-subtitle").textContent = "上传文本后，系统会切分章节、建立阅读进度并自动构建 temporal knowledge graph。";
    document.getElementById("progress-text").textContent = "当前还没有激活的阅读进度。";
    document.getElementById("hero-chapter").textContent = "-";
    document.getElementById("hero-paragraph").textContent = "-";
    document.getElementById("hero-dwell").textContent = "0s";
    return;
  }
  const pages = getCurrentPages();
  document.getElementById("book-title").textContent = state.activeBookDetail.title;
  document.getElementById("book-subtitle").textContent = `book_id: ${state.activeBookDetail.book_id}，共 ${state.activeBookDetail.chapter_count} 章。`;
  document.getElementById("progress-text").textContent =
    `当前位于第 ${state.readingProgress.chapter_id} 章 / 第 ${state.activePageIndex + 1} 页 / 段落 ${state.readingProgress.paragraph_id || "-"}，本章共 ${pages.length || 0} 页。`;
  document.getElementById("hero-chapter").textContent = `第 ${state.activeChapter} 章`;
  document.getElementById("hero-paragraph").textContent = state.activeParagraphIndex === null ? "-" : `P${state.activeParagraphIndex}`;
  document.getElementById("hero-dwell").textContent = `${state.readingProgress.dwell_seconds || 0}s`;
}

function renderChapterNav() {
  const container = document.getElementById("chapter-nav");
  container.innerHTML = "";
  if (!state.activeBookDetail) {
    container.innerHTML = '<p class="muted">上传或选择一本书后，这里会显示章节目录。</p>';
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

  getCurrentPassages().forEach((passage, index) => {
    const option = document.createElement("option");
    const paragraphIndex = passage.paragraph_index ?? index + 1;
    option.value = String(paragraphIndex);
    option.textContent = `段落 ${paragraphIndex}`;
    paragraphSelect.appendChild(option);
  });
  if (state.activeParagraphIndex !== null) {
    paragraphSelect.value = String(state.activeParagraphIndex);
  }
}

function renderSelectionPreview() {
  document.getElementById("highlight-preview").textContent = previewText(
    state.selectionContext.selected_text,
    "点击正文中的任意段落，这里会显示当前选中的文本。"
  );
}

function renderAssistantStatus() {
  const node = document.getElementById("assistant-status");
  if (state.assistantMode === "persona") {
    const persona = getPersonaById(state.personaId);
    node.textContent = persona ? `当前由 ${persona.name} 负责名家导读。` : "当前由名家导读模式回答。";
  } else if (state.activeCharacterProfile) {
    node.textContent = `当前由角色 ${state.activeCharacterProfile.character_name} 负责陪读。`;
  } else if (state.activeCharacterName) {
    node.textContent = `当前准备生成角色 ${state.activeCharacterName} 的陪读画像。`;
  } else {
    node.textContent = "先选择或生成一个角色画像，再切到角色陪读模式。";
  }
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
    historyNode.innerHTML = '<p class="muted">这里会连续显示名家导读或角色陪读的对话记录。</p>';
    return;
  }
  conversation.forEach((turn) => {
    const item = document.createElement("article");
    item.className = `chat-message chat-message-${turn.role}`;
    const role =
      turn.role === "user"
        ? "User"
        : state.assistantMode === "persona"
          ? getPersonaById(state.personaId)?.name || "Persona Agent"
          : state.activeCharacterProfile?.character_name || state.activeCharacterName || "Character Agent";
    item.innerHTML = `
      <div class="chat-role">${role}</div>
      <div class="chat-content">${turn.content.replace(/\n/g, "<br />")}</div>
    `;
    historyNode.appendChild(item);
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

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function createInlineBubbleMarkup(text, chunkId) {
  const bubbles = (state.inlineBubblesByChunk[chunkId] || [])
    .map((bubble) => ({ ...bubble, index: text.indexOf(bubble.anchor_text) }))
    .filter((bubble) => bubble.index >= 0)
    .sort((left, right) => left.index - right.index);

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
      <span class="inline-bubble" data-bubble-id="${bubble.bubble_id}">
        <button
          class="inline-bubble-anchor"
          type="button"
          data-bubble-id="${bubble.bubble_id}"
          aria-label="${escapeHtml(bubble.label)}"
        >${escapeHtml(bubble.anchor_text)}</button>
        <span class="inline-bubble-tip" data-bubble-id="${bubble.bubble_id}">
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
  document.querySelectorAll(".inline-bubble-anchor").forEach((node) => {
    node.addEventListener("click", (event) => {
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
    container.innerHTML = '<p class="muted">当前章节还没有可显示的内容。</p>';
    return;
  }

  const page = document.createElement("article");
  page.className = "reading-page";
  page.innerHTML = `
    <header class="reading-page-header">
      <span>第 ${state.activeChapter} 章</span>
      <span>第 ${state.activePageIndex + 1} 页</span>
    </header>
  `;

  pageItems.forEach((passage, index) => {
    const paragraphIndex = passage.paragraph_index ?? passage._index + 1;
    const wrapper = document.createElement("article");
    wrapper.className = `reading-paragraph ${paragraphIndex === state.activeParagraphIndex ? "is-selected" : ""}`;
    wrapper.dataset.paragraphIndex = String(paragraphIndex);
    wrapper.innerHTML = `
      <span class="paragraph-marker">${paragraphIndex}</span>
      <div class="reading-paragraph-text">${createInlineBubbleMarkup(passage.text, passage.chunk_id)}</div>
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
  updateProgressFromSelection(passage);
  buildSelectionFromPassage(passage, index, passages);
  renderSelectionPreview();
  renderReaderHeader();
  renderPassages();
}

function setPage(pageIndex) {
  const pages = getCurrentPages();
  if (!pages.length) {
    state.activePageIndex = 0;
    renderPassages();
    return;
  }
  state.activePageIndex = Math.max(0, Math.min(pageIndex, pages.length - 1));
  const currentItems = getCurrentPageItems();
  const firstVisible = currentItems[0];
  if (firstVisible) {
    state.activeParagraphIndex = firstVisible.paragraph_index ?? firstVisible._index + 1;
    updateProgressFromSelection(firstVisible);
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
  const payload = {
    book_id: state.activeBook,
    current_chapter: state.activeChapter,
    visible_chunk_ids: pageItems.map((item) => item.chunk_id),
    persona_id: state.personaId,
    assistant_mode: state.assistantMode,
    character_name: state.activeCharacterName,
    max_bubbles: 3,
  };
  try {
    const bubbles = await fetchJSON(`/api/books/${state.activeBook}/inline-bubbles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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
    console.error("bubble generation failed", error);
  }
}

async function loadCharacterCandidates() {
  if (!state.activeBook) {
    state.characterCandidates = [];
    renderCharacterCandidates();
    return;
  }
  setButtonLoading("character-generate-btn", true, "正在读取角色候选...");
  try {
    state.characterCandidates = await fetchJSON(
      `/api/books/${state.activeBook}/characters?current_chapter=${state.activeChapter}&limit=12`
    );
    renderCharacterCandidates();
  } catch (error) {
    state.characterCandidates = [];
    renderCharacterCandidates();
    document.getElementById("character-profile-card").innerHTML = `<p class="muted">角色候选读取失败：${error.message}</p>`;
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
      '<p class="muted">请先选择一个角色，或手动输入角色名后再生成画像。</p>';
    return;
  }
  state.activeCharacterName = characterName;
  renderAssistantStatus();
  setButtonLoading("character-generate-btn", true, "正在生成角色画像...");
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
    finishPendingWorkflow("done", "Character Profile Ready", "角色画像已经生成，可以直接继续角色陪读。");
  } catch (error) {
    document.getElementById("character-profile-card").innerHTML = `<p class="muted">角色画像生成失败：${error.message}</p>`;
    setPendingState(false, "idle");
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
}

async function loadPersonas() {
  state.personas = await fetchJSON("/api/personas");
  const select = document.getElementById("persona-select");
  select.innerHTML = state.personas.map((persona) => `<option value="${persona.persona_id}">${persona.name}</option>`).join("");
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
  renderBooks();
  renderChatHistory();
  await setActiveChapter(getFirstReadableChapter());
}

async function uploadBook(event) {
  event.preventDefault();
  const input = document.getElementById("file-input");
  if (!input.files[0]) {
    return;
  }
  setPendingState(true, "starting-upload");
  try {
    const payload = new FormData();
    payload.append("file", input.files[0]);
    const job = await fetchJSON("/api/upload-jobs", { method: "POST", body: payload });
    applyUploadJobState(job);
    const uploaded = await waitForUploadJob(job.job_id);
    await loadBooks();
    await openBook(uploaded.book_id);
    input.value = "";
    finishPendingWorkflow(
      "done",
      "Temporal Graph Ready",
      `《${uploaded.book_title || uploaded.title}》已经完成章节切分、episode 构建与 temporal graph 写入。`
    );
  } catch (error) {
    pushConversation("assistant", `导入失败：${error.message}`);
    renderChatHistory();
    setPendingState(false, "idle");
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
  setButtonLoading("ask-btn", true, "正在思考...");
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
        throw new Error("请先生成或选择一个角色画像，再发起角色陪读问答。");
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
      state.assistantMode === "persona" ? "Persona Answer Ready" : "Character Answer Ready",
      state.assistantMode === "persona"
        ? "名家 agent 已完成图谱检索、persona RAG 与防剧透过滤后的回答。"
        : "角色陪读 agent 已完成当前可见范围内的角色化回答。"
    );
  } catch (error) {
    pushConversation("assistant", `问答失败：${error.message}`);
    renderChatHistory();
    setPendingState(false, "idle");
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
  setButtonLoading("summary-btn", true, "正在生成总结...");
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
    finishPendingWorkflow("done", "Chapter Summary Ready", "当前章节总结已经基于已读 episode 与时序图状态生成完成。");
  } catch (error) {
    pushConversation("assistant", `章节总结失败：${error.message}`);
    renderChatHistory();
    setPendingState(false, "idle");
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
  await loadPersonas();
  await loadBooks();
  if (state.books[0]) {
    await openBook(state.books[0].book_id);
  }
}

bootstrap().catch((error) => {
  console.error(error);
});

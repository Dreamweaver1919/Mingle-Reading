const CHARS_PER_PAGE = 1150;
const REQUEST_TIMEOUT_MS = 300000;
const WORKFLOW_TICK_MS = 900;

const PENDING_WORKFLOWS = {
  idle: {
    title: "Idle",
    description: "绛夊緟鐢ㄦ埛鍙戣捣涓婁紶銆侀棶绛旀垨鎬荤粨璇锋眰銆?,
    steps: [],
  },
  uploadGraph: {
    title: "Graphiti Temporal Graph Build",
    description: "姝ｅ湪鎶婁笂浼犳枃鏈浆鎹㈡垚 Graphiti 椋庢牸鐨勬椂搴忕煡璇嗗浘璋卞熀搴с€?,
    steps: [
      { name: "Extract source text", copy: "璇诲彇 TXT / PDF / EPUB锛屽苟鎻愬彇鍚庣画寤哄浘鎵€闇€鐨勬鏂囥€? },
      { name: "Segment chapters", copy: "鎸夌珷鑺傚拰娈佃惤鍒囧垎鏂囨湰锛屽缓绔嬬ǔ瀹氱殑闃呰杈圭晫銆? },
      { name: "Construct episodes", copy: "鎶婃钀借浆鎹负 canonical episodes锛屽苟涓茶捣 narrative order銆? },
      { name: "Resolve entities", copy: "缁撳悎宸叉湁鍥捐妭鐐瑰拰涓婁笅鏂囷紝鍋?LLM-assisted entity resolution銆? },
      { name: "Resolve facts", copy: "鎶藉彇浜虹墿銆佸湴鐐广€佸叧绯诲拰鐘舵€佷簨瀹烇紝骞跺仛 temporal invalidation銆? },
      { name: "Build communities", copy: "姹囨€?chapter timeline銆乧ommunity 鍜?saga 缁撴瀯銆? },
      { name: "Build sagas", copy: "鎶婅法绔犺妭鐨勫彊浜嬩富绾挎暣鐞嗘垚 saga 绾х粨鏋勩€? },
      { name: "Assemble chapter timeline", copy: "鎶?episode銆乪ntity 鍜?relation 姹囨€绘垚绔犺妭鏃堕棿绾裤€? },
      { name: "Serialize graph payload", copy: "鎶婂唴瀛樹腑鐨勫浘鑺傜偣銆佽竟鍜屽厓鏁版嵁搴忓垪鍖栦负鍙惤鐩樻牸寮忋€? },
      { name: "Persist book record", copy: "鍏堝啓鍏?book record锛屽浐瀹氱珷鑺傘€佹钀藉拰闃呰瑙嗗浘鏁版嵁銆? },
      { name: "Persist graph snapshot", copy: "鍐欏叆 temporal graph 蹇収銆乺elations銆乧ommunities 鍜?sagas銆? },
      { name: "Finalize graph metadata", copy: "鏀跺熬鍥剧粺璁°€乻torage metadata 鍜屽墠绔彲璇荤储寮曘€? },
    ],
  },
  personaQa: {
    title: "Persona Answering",
    description: "姝ｅ湪缁勫悎涔︽湰涓婁笅鏂囥€佸悕瀹?persona RAG 鍜岄槻鍓ч€忕害鏉熴€?,
    steps: [
      { name: "Read current scope", copy: "瀹氫綅褰撳墠绔犺妭銆侀珮浜拰鍙涓婁笅鏂囥€? },
      { name: "Retrieve graph context", copy: "浠?temporal graph 妫€绱㈠綋鍓嶉棶棰樼浉鍏崇殑宸茶浜嬪疄銆? },
      { name: "Retrieve persona context", copy: "鍙洖鍚嶅璧勬枡鐗囨鍜岄鏍艰瘉鎹€? },
      { name: "Apply spoiler guard", copy: "鏍规嵁褰撳墠杩涘害杩囨护鏈潵淇℃伅锛屽彧淇濈暀鍙鑼冨洿銆? },
      { name: "Generate answer", copy: "缁勭粐鎴愬畬鏁村悕瀹跺洖绛斿苟鍐欏洖瀵硅瘽鍖恒€? },
    ],
  },
  characterQa: {
    title: "Character Companion Answering",
    description: "姝ｅ湪璁╀功涓鑹插湪褰撳墠宸茶杈圭晫鍐呰繘琛岄櫔璇诲洖搴斻€?,
    steps: [
      { name: "Read visible scope", copy: "瀹氫綅褰撳墠绔犺妭鍜岀敤鎴烽珮浜搴旂殑鍙鏂囨湰銆? },
      { name: "Resolve character memory", copy: "妫€绱㈣鑹插湪褰撳墠杩涘害鍓嶅凡缁忓嚭鐜扮殑浜嬩欢鍜屽叧绯汇€? },
      { name: "Apply spoiler guard", copy: "杩囨护瑙掕壊鏈潵鍛借繍鍜屽悗鏂囨湭鎻ず淇℃伅銆? },
      { name: "Generate answer", copy: "浠ヨ鑹茶韩浠借緭鍑鸿繛缁櫔璇诲洖绛斻€? },
    ],
  },
  chapterSummary: {
    title: "Chapter Summary",
    description: "姝ｅ湪鏍规嵁褰撳墠宸茶鍐呭鐢熸垚闃舵鎬ф€荤粨銆?,
    steps: [
      { name: "Collect chapter episodes", copy: "鏀堕泦褰撳墠绔犺妭宸茶娈佃惤鍜岀浉閭昏瘉鎹€? },
      { name: "Read graph state", copy: "鏁寸悊浜虹墿銆佸叧绯诲拰涓婚鍦ㄦ湰绔犵殑灞€閮ㄦ紨鍖栥€? },
      { name: "Apply spoiler guard", copy: "闃绘柇鏈潵绔犺妭淇℃伅锛屽彧鎬荤粨褰撳墠鍙鑼冨洿銆? },
      { name: "Generate summary", copy: "杈撳嚭闃舵鎬荤粨骞跺啓鍏ュ璇濊褰曘€? },
    ],
  },
  characterProfile: {
    title: "Character Profile Build",
    description: "姝ｅ湪鏍规嵁褰撳墠宸茶鏂囨湰鐢熸垚瑙掕壊鐢诲儚銆?,
    steps: [
      { name: "Find character evidence", copy: "鍦ㄥ綋鍓嶅凡璇昏寖鍥村唴瀹氫綅瑙掕壊鍑虹幇鐨勮瘉鎹钀姐€? },
      { name: "Assemble relation view", copy: "姹囨€昏瑙掕壊鍙鐨勪汉鐗╁叧绯诲拰寮犲姏銆? },
      { name: "Generate profile", copy: "鐢熸垚鐢ㄤ簬鍓嶇鍙鍖栫殑瑙掕壊鍗＄墖銆? },
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
  graphViewVisible: false,
  graphViewScope: "chapter",
  graphViewData: null,
  graphViewLoading: false,
  graphViewError: "",
  graphSelection: null,
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
      throw new Error(`璇锋眰绛夊緟瓒呰繃 ${REQUEST_TIMEOUT_MS / 1000}s銆俙);
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
    pendingTitle.textContent = "Idle";
    pendingDescription.textContent = "上传文档后，这里会显示文本抽取、文段构建、LLM 抽取和知识图谱写入的实时进度。";
    pendingBar.style.width = "0%";
    pendingPercent.textContent = "0%";
    pendingStepCaption.textContent = "等待新的处理任务开始。";
    indicator.classList.remove("is-active", "is-indeterminate");
    return;
  }

  indicator.classList.add("is-active");
  indicator.classList.toggle("is-indeterminate", workflow.indeterminate === true);
  pendingLabel.textContent = workflow.label || "running";
  pendingTitle.textContent = workflow.title || "Processing";
  pendingDescription.textContent = workflow.description || "系统正在处理当前任务。";
  pendingBar.style.width = workflow.indeterminate ? "32%" : `${workflow.percent || 0}%`;
  pendingPercent.textContent = `${workflow.percent || 0}%`;
  pendingStepCaption.textContent = (workflow.currentStep && workflow.currentStep.copy) || "正在等待下一条状态更新。";
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
    description: "系统正在启动当前任务。",
    steps: [],
    currentIndex: -1,
    currentStep: { name: "starting", copy: "正在连接处理管线，请稍候。" },
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
    title: template.title || "Processing",
    description: template.description || "系统正在处理当前任务。",
    steps,
    currentIndex: 0,
    currentStep: steps[0] || { name: "running", copy: "正在处理中。" },
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

function finishPendingWorkflow(label = "done", title = "Completed", description = "任务已完成。") {
  clearPendingWorkflowTimer();
  if (!state.pendingWorkflow) {
    return;
  }
  const lastIndex = Math.max(0, (state.pendingWorkflow.steps || []).length - 1);
  state.pendingWorkflow = {
    ...state.pendingWorkflow,
    label,
    title,
    description,
    currentIndex: lastIndex,
    currentStep: (state.pendingWorkflow.steps || [])[lastIndex] || state.pendingWorkflow.currentStep,
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

const UPLOAD_STAGE_META = {
  queued: {
    title: "Upload queued",
    description: "绛夊緟鍚庣寮€濮嬪鐞嗕笂浼犳枃浠躲€?,
  },
  "extract-source-text": {
    title: "Extracting source text",
    description: "姝ｅ湪璇诲彇 TXT / PDF / EPUB 骞舵娊鍙栨鏂囥€?,
  },
  "segment-chapters": {
    title: "Segmenting chapters",
    description: "姝ｅ湪璇嗗埆绔犺妭杈圭晫骞舵暣鐞嗘钀姐€?,
  },
  "construct-episodes": {
    title: "Building constrained packets",
    description: "姝ｅ湪鎸夌珷鑺傚唴閭绘帴瑙勫垯鍚堝苟娈佃惤锛岀敓鎴愮敤浜庣煡璇嗗浘璋辨娊鍙栫殑 episodes銆?,
  },
  "graph-episode-start": {
    title: "Processing episode",
    description: "姝ｅ湪澶勭悊褰撳墠鏂囨锛屽噯澶囪繘鍏ュ疄浣撲笌浜嬪疄鎶藉彇銆?,
  },
  "llm-skipped": {
    title: "LLM gate skipped this episode",
    description: "褰撳墠鏂囨淇″彿杈冨急锛屽凡閫氳繃楂樼簿搴﹂棬鎺ц烦杩囧ぇ妯″瀷璋冪敤銆?,
  },
  "llm-request-dispatched": {
    title: "Waiting for LLM extraction",
    description: "宸茬粡鍚戞ā鍨嬫彁浜?entity / fact extraction prompt锛屾鍦ㄧ瓑寰呯粨鏋勫寲 JSON 杩斿洖銆?,
  },
  "llm-response-received": {
    title: "LLM extraction received",
    description: "宸叉敹鍒扮粨鏋勫寲瀹炰綋涓庝簨瀹炲€欓€夛紝姝ｅ湪鍐欏洖褰撳墠鏂囨鍥捐氨銆?,
  },
  "llm-request-failed": {
    title: "LLM extraction failed",
    description: "褰撳墠鏂囨鐨勫ぇ妯″瀷鎶藉彇澶辫触锛岃妫€鏌ヤ笂娓告ā鍨嬫湇鍔℃垨 JSON 杈撳嚭銆?,
  },
  "graph-episode-complete": {
    title: "Episode graph updated",
    description: "褰撳墠鏂囨鐨勫疄浣撱€佸叧绯诲拰鏃跺簭鐘舵€佸凡缁忓啓鍏ュ浘璋卞唴瀛樸€?,
  },
  "chapter-consolidation": {
    title: "Chapter consolidation",
    description: "姝ｅ湪鍋氱珷鑺傜骇鍒悕褰掑苟銆佸叧绯诲幓閲嶄笌鐘舵€佸啿绐佹秷瑙ｃ€?,
  },
  "graph-community-build": {
    title: "Building communities",
    description: "姝ｅ湪浠庣珷鑺備笌瀹炰綋鍏崇郴涓敓鎴?community 鑱氬悎灞傘€?,
  },
  "graph-saga-build": {
    title: "Building sagas",
    description: "姝ｅ湪鐢熸垚璺ㄧ珷鑺傜殑 saga 鍙欎簨鑱氬悎灞傘€?,
  },
  "graph-timeline-build": {
    title: "Building chapter timeline",
    description: "姝ｅ湪瑁呴厤 chapter timeline 涓?active / invalidated facts 瑙嗗浘銆?,
  },
  "graph-build-finished": {
    title: "Graph build finished",
    description: "鍥捐氨鍐呭瓨鏋勫缓瀹屾垚锛屽噯澶囧啓鍏ユ寔涔呭寲瀛樺偍銆?,
  },
  "persist-book-record": {
    title: "Persisting book record",
    description: "姝ｅ湪淇濆瓨瑙ｆ瀽鍚庣殑涔︾睄缁撴瀯涓?episode 璁板綍銆?,
  },
  "persist-graph-snapshot": {
    title: "Persisting graph snapshot",
    description: "姝ｅ湪淇濆瓨 temporal graph snapshot銆乺elations銆乧ommunities 涓?sagas銆?,
  },
  "finalize-upload": {
    title: "Finalizing upload",
    description: "姝ｅ湪鍐欏叆鏈€缁堝厓鏁版嵁骞剁粨鏉熸湰娆℃瀯鍥句换鍔°€?,
  },
  completed: {
    title: "Temporal graph ready",
    description: "涓婁紶銆佸垏鍒嗕笌鐭ヨ瘑鍥捐氨鏋勫缓宸插畬鎴愩€?,
  },
  failed: {
    title: "Upload failed",
    description: "涓婁紶浠诲姟澶辫触锛岃鏌ョ湅褰撳墠闃舵鍜岄敊璇鎯呫€?,
  },
};

function formatSourceParagraphSummary(details = {}) {
  const sourceCount = Number(details.source_paragraph_count || 0);
  const sourceIndices = Array.isArray(details.source_paragraph_indices) ? details.source_paragraph_indices : [];
  const packetTokens = Number(details.packet_token_count || 0);
  if (!sourceCount && !packetTokens) {
    return "";
  }
  const rangeLabel =
    sourceIndices.length > 1
      ? `${sourceIndices[0]}-${sourceIndices[sourceIndices.length - 1]}`
      : sourceIndices.length === 1
      ? String(sourceIndices[0])
      : "-";
  const mergedLabel = details.is_merged_packet ? "merged packet" : "single paragraph";
  const tokenLabel = packetTokens ? `, ${packetTokens} chars` : "";
  return `婧愭枃娈?${rangeLabel}锛?{sourceCount || 1} 娈碉紝${mergedLabel}${tokenLabel}锛塦;
}

function formatGateSummary(details = {}) {
  if (!details || typeof details !== "object") {
    return "";
  }
  const reasons = Array.isArray(details.reasons) ? details.reasons.filter(Boolean) : [];
  const score = typeof details.score === "number" ? details.score : null;
  const threshold = typeof details.threshold === "number" ? details.threshold : null;
  if (score === null && !reasons.length) {
    return "";
  }
  const scoreLabel = score !== null && threshold !== null ? `gate ${score}/${threshold}` : "gate";
  const reasonLabel = reasons.length ? `锛?{reasons.join(", ")}` : "";
  return `${scoreLabel}${reasonLabel}`;
}

function formatUploadStageCopy(job) {
  const processed = Number(job.processed_snippets || 0);
  const total = Number(job.total_snippets || 0);
  const details = job.details || {};
  const currentSnippet = job.current_snippet_id
    ? `褰撳墠鏂囨 ${job.current_snippet_id}锛坈hapter ${job.current_chapter_index || "-"} / paragraph ${job.current_paragraph_index || "-"}锛塦
    : "";
  const processedLabel = total ? `宸插鐞嗘枃娈?${processed}/${total}` : "";
  const packetSummary = formatSourceParagraphSummary(details);
  const gateSummary = formatGateSummary(details);
  const llmDispatch =
    job.stage === "llm-request-dispatched"
      ? `LLM provider: ${details.provider || "configured runtime"}锛宲rompt 宸蹭氦浠橈紝绛夊緟杩斿洖`
      : "";
  const llmResponse =
    job.stage === "llm-response-received"
      ? `LLM 杩斿洖 ${details.entity_candidates || 0} 涓疄浣撳€欓€夛紝${details.fact_candidates || 0} 鏉′簨瀹炲€欓€塦
      : "";
  const llmFailure = job.stage === "llm-request-failed" && details.error ? `閿欒锛?{details.error}` : "";
  const consolidation =
    job.stage === "chapter-consolidation"
      ? `绔犺妭鏁?${details.chapter_count || "-"}锛屽綋鍓嶅浘涓疄浣?${details.active_entity_count || 0}锛屽叧绯?${details.active_relation_count || 0}`
      : "";
  const persistence =
    job.stage === "persist-graph-snapshot"
      ? `瀹炰綋 ${details.entity_count || 0}锛屽叧绯?${details.relation_count || 0}锛宑ommunity ${details.community_count || 0}锛宻aga ${details.saga_count || 0}`
      : "";

  return [
    processedLabel,
    currentSnippet,
    packetSummary,
    gateSummary,
    llmDispatch,
    llmResponse,
    llmFailure,
    consolidation,
    persistence,
  ]
    .filter(Boolean)
    .join(" | ");
}

function applyUploadJobState(job) {
  const stage = job.stage || job.status || "queued";
  const stageMeta = UPLOAD_STAGE_META[stage] || {
    title: job.title || "Temporal graph build",
    description: job.message || "",
  };
  state.pendingWorkflow = {
    key: "uploadGraph",
    label: stage,
    title: job.title || stageMeta.title,
    description: job.message || stageMeta.description,
    percent: job.percent || 0,
    indeterminate: false,
    currentIndex: 0,
    currentStep: {
      name: stage,
      copy: formatUploadStageCopy(job),
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

function previewText(text, fallback = "杩樻病鏈夐€変腑鐨勬枃鏈?) {
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
  emptyOption.textContent = state.characterCandidates.length ? "璇烽€夋嫨瑙掕壊鍊欓€? : "鏆傛棤瑙掕壊鍊欓€?;
  select.appendChild(emptyOption);

  state.characterCandidates.forEach((candidate) => {
    const option = document.createElement("option");
    option.value = candidate.character_name;
    option.textContent = `${candidate.character_name} 路 ${candidate.mention_count} 娆;
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
    container.innerHTML = '<p class="muted">鐢熸垚瑙掕壊鐢诲儚鍚庯紝杩欓噷浼氬睍绀哄綋鍓嶅凡璇昏寖鍥村唴鐨勮鑹叉憳瑕併€佸紶鍔涘拰鍏崇郴銆?/p>';
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
    li.textContent = `${relation.target}锛?{relation.description}`;
    relationList.appendChild(li);
  });

  container.innerHTML = `
    <h4 class="character-name">${profile.character_name}</h4>
    <p class="muted">${profile.summary}</p>
    <p class="label">鏍稿績寮犲姏</p>
    <p class="signature-tension">${profile.signature_tension || "褰撳墠宸茶鑼冨洿鍐呰繕娌℃湁瓒冲鐨勮鑹插啿绐佹弿杩般€?}</p>
    <p class="label">褰撳墠鍙鑼冨洿</p>
    <p class="muted">${profile.current_scope}</p>
    <p class="label">妯″瀷</p>
    <p class="muted">${profile.model_name}</p>
  `;
  container.appendChild(traitRow);
  if (relationList.children.length) {
    const heading = document.createElement("p");
    heading.className = "label";
    heading.textContent = "浜虹墿鍏崇郴";
    container.appendChild(heading);
    container.appendChild(relationList);
  }
}

function renderBooks() {
  const list = document.getElementById("book-list");
  list.innerHTML = "";
  document.getElementById("book-count").textContent = `${state.books.length} 鏈琡;
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
    document.getElementById("book-title").textContent = "閫夋嫨涓€鏈功寮€濮嬮槄璇?;
    document.getElementById("book-subtitle").textContent = "涓婁紶鏂囨湰鍚庯紝绯荤粺浼氬垏鍒嗙珷鑺傘€佸缓绔嬮槄璇昏繘搴﹀苟鑷姩鏋勫缓 temporal knowledge graph銆?;
    document.getElementById("progress-text").textContent = "褰撳墠杩樻病鏈夋縺娲荤殑闃呰杩涘害銆?;
    document.getElementById("hero-chapter").textContent = "-";
    document.getElementById("hero-paragraph").textContent = "-";
    document.getElementById("hero-dwell").textContent = "0s";
    return;
  }
  const pages = getCurrentPages();
  document.getElementById("book-title").textContent = state.activeBookDetail.title;
  document.getElementById("book-subtitle").textContent = `book_id: ${state.activeBookDetail.book_id}锛屽叡 ${state.activeBookDetail.chapter_count} 绔犮€俙;
  document.getElementById("progress-text").textContent =
    `褰撳墠浣嶄簬绗?${state.readingProgress.chapter_id} 绔?/ 绗?${state.activePageIndex + 1} 椤?/ 娈佃惤 ${state.readingProgress.paragraph_id || "-"}锛屾湰绔犲叡 ${pages.length || 0} 椤点€俙;
  document.getElementById("hero-chapter").textContent = `绗?${state.activeChapter} 绔燻;
  document.getElementById("hero-paragraph").textContent = state.activeParagraphIndex === null ? "-" : `P${state.activeParagraphIndex}`;
  document.getElementById("hero-dwell").textContent = `${state.readingProgress.dwell_seconds || 0}s`;
}

function renderChapterNav() {
  const container = document.getElementById("chapter-nav");
  container.innerHTML = "";
  if (!state.activeBookDetail) {
    container.innerHTML = '<p class="muted">涓婁紶鎴栭€夋嫨涓€鏈功鍚庯紝杩欓噷浼氭樉绀虹珷鑺傜洰褰曘€?/p>';
    return;
  }
  for (let chapter = 1; chapter <= state.activeBookDetail.chapter_count; chapter += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chapter-button ${chapter === state.activeChapter ? "is-active" : ""}`;
    button.textContent = `绗?${chapter} 绔燻;
    button.addEventListener("click", () => setActiveChapter(chapter));
    container.appendChild(button);
  }
  document.getElementById("toc-progress").textContent = `宸茶鑷崇 ${state.activeChapter} 绔燻;
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
    option.textContent = `绗?${chapter} 绔燻;
    chapterSelect.appendChild(option);
  }
  chapterSelect.value = String(state.activeChapter);

  getCurrentPassages().forEach((passage, index) => {
    const option = document.createElement("option");
    const paragraphIndex = passage.paragraph_index ?? index + 1;
    option.value = String(paragraphIndex);
    option.textContent = `娈佃惤 ${paragraphIndex}`;
    paragraphSelect.appendChild(option);
  });
  if (state.activeParagraphIndex !== null) {
    paragraphSelect.value = String(state.activeParagraphIndex);
  }
}

function renderSelectionPreview() {
  document.getElementById("highlight-preview").textContent = previewText(
    state.selectionContext.selected_text,
    "鐐瑰嚮姝ｆ枃涓殑浠绘剰娈佃惤锛岃繖閲屼細鏄剧ず褰撳墠閫変腑鐨勬枃鏈€?
  );
}

function renderAssistantStatus() {
  const node = document.getElementById("assistant-status");
  if (state.assistantMode === "persona") {
    const persona = getPersonaById(state.personaId);
    node.textContent = persona ? `褰撳墠鐢?${persona.name} 璐熻矗鍚嶅瀵艰銆俙 : "褰撳墠鐢卞悕瀹跺璇绘ā寮忓洖绛斻€?;
  } else if (state.activeCharacterProfile) {
    node.textContent = `褰撳墠鐢辫鑹?${state.activeCharacterProfile.character_name} 璐熻矗闄銆俙;
  } else if (state.activeCharacterName) {
    node.textContent = `褰撳墠鍑嗗鐢熸垚瑙掕壊 ${state.activeCharacterName} 鐨勯櫔璇荤敾鍍忋€俙;
  } else {
    node.textContent = "鍏堥€夋嫨鎴栫敓鎴愪竴涓鑹茬敾鍍忥紝鍐嶅垏鍒拌鑹查櫔璇绘ā寮忋€?;
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
    historyNode.innerHTML = '<p class="muted">杩欓噷浼氳繛缁樉绀哄悕瀹跺璇绘垨瑙掕壊闄鐨勫璇濊褰曘€?/p>';
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

function graphNodeColor(type) {
  if (type === "character") return "#1f6a73";
  if (type === "theme" || type === "concept") return "#8f5a3c";
  if (type === "location") return "#546c44";
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
  if (!panel || !canvas || !detail || !badge || !caption || !toggleButton || !chapterScopeButton || !bookScopeButton) {
    return;
  }

  chapterScopeButton.classList.toggle("is-active", state.graphViewScope === "chapter");
  bookScopeButton.classList.toggle("is-active", state.graphViewScope === "book");

  panel.classList.toggle("is-hidden", !state.graphViewVisible);
  toggleButton.textContent = state.graphViewVisible ? "闅愯棌鐭ヨ瘑鍥捐氨" : "鏄剧ず鐭ヨ瘑鍥捐氨";

  if (!state.graphViewVisible) {
    return;
  }

  if (state.graphViewLoading) {
    badge.textContent = "loading";
    canvas.innerHTML = '<p class="muted">姝ｅ湪璇诲彇褰撳墠绔犺妭鐨勭煡璇嗗浘璋?..</p>';
    detail.textContent = "鍥捐氨鍔犺浇瀹屾垚鍚庯紝杩欓噷浼氭樉绀鸿妭鐐规垨杈圭殑鎽樿銆?;
    return;
  }

  if (state.graphViewError) {
    badge.textContent = "error";
    canvas.innerHTML = `<p class="muted">鐭ヨ瘑鍥捐氨璇诲彇澶辫触锛?{escapeHtml(state.graphViewError)}</p>`;
    detail.textContent = "璇风◢鍚庨噸璇曪紝鎴栧厛纭褰撳墠涔﹀凡缁忔垚鍔熷畬鎴愮煡璇嗗浘璋辨瀯寤恒€?;
    return;
  }

  const data = state.graphViewData;
  const scopeLabel = state.graphViewScope === "book" ? "全书总图" : "当前章节图";
  if (!data || !Array.isArray(data.nodes) || !data.nodes.length) {
    badge.textContent = "0 nodes";
    canvas.innerHTML = `<p class="muted">${scopeLabel}当前还没有足够清晰的图谱节点可显示。</p>`;
    detail.textContent = state.graphViewScope === "book"
      ? "这本书已经完成建图，但在当前可见进度内还没有稳定到足以展示的节点和关系。"
      : "当前章节图为空时，可以直接切到全书总图，避免被单章的稀疏图谱误导。";
    return;
  }

  badge.textContent = `${data.stats.node_count} nodes / ${data.stats.edge_count} edges`;
  caption.textContent = state.graphViewScope === "book"
    ? `当前显示全书总图，展示截至当前阅读进度可见的全书节点与关系，共有 ${data.stats.node_count} 个节点和 ${data.stats.edge_count} 条边。`
    : `当前显示第 ${data.chapter_index} 章的局部知识图谱，共有 ${data.stats.node_count} 个节点和 ${data.stats.edge_count} 条边。`;

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

  const edgeMarkup = data.edges
    .map((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      if (!source || !target) {
        return "";
      }
      const midX = (source.x + target.x) / 2;
      const midY = (source.y + target.y) / 2;
      return `
        <g class="graph-edge-group" data-edge-id="${edge.id}">
          <line
            class="graph-edge ${edge.status !== "active" ? "is-invalidated" : ""}"
            x1="${source.x}"
            y1="${source.y}"
            x2="${target.x}"
            y2="${target.y}"
            data-edge-id="${edge.id}"
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
        <g class="graph-node" data-node-id="${node.id}">
          <circle
            class="graph-node-circle type-${escapeHtml(node.type || "unknown")}"
            cx="${position.x}"
            cy="${position.y}"
            r="${size}"
            data-node-id="${node.id}"
          ></circle>
          <text class="graph-node-label" x="${position.x}" y="${position.y + size + 14}">${escapeHtml(node.label)}</text>
        </g>
      `;
    })
    .join("");

  const communityMarkup = Array.isArray(data.communities) && data.communities.length
    ? `<div class="graph-community-summary"><strong>Communities:</strong> ${data.communities
        .map((item) => `${escapeHtml(item.label)} (${item.entity_count})`)
        .join(" / ")}</div>`
    : "";

  canvas.innerHTML = `
    <svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="knowledge graph view">
      ${edgeMarkup}
      ${nodeMarkup}
    </svg>
    ${communityMarkup}
  `;

  detail.textContent = "鐐瑰嚮鑺傜偣鏌ョ湅浜虹墿/姒傚康鎽樿锛岀偣鍑昏竟鏌ョ湅鍏崇郴浜嬪疄銆?;

  canvas.querySelectorAll("[data-node-id]").forEach((nodeElement) => {
    nodeElement.addEventListener("click", (event) => {
      const nodeId = event.currentTarget.dataset.nodeId;
      const node = data.nodes.find((item) => item.id === nodeId);
      if (!node) {
        return;
      }
      state.graphSelection = { kind: "node", id: nodeId };
      detail.innerHTML = `
        <strong>${escapeHtml(node.label)}</strong> 路 ${escapeHtml(node.type || "entity")}<br />
        鎻愬強娆℃暟锛?{node.mention_count || 0}<br />
        棣栨鍑虹幇锛氱 ${node.first_seen_chapter || "-"} 绔?/ 娈佃惤 ${node.first_seen_paragraph || "-"}<br />
        ${escapeHtml(node.summary || "褰撳墠杩樻病鏈変负杩欎釜鑺傜偣鐢熸垚鎽樿銆?)}
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
      state.graphSelection = { kind: "edge", id: edgeId };
      detail.innerHTML = `
        <strong>${escapeHtml(edge.label)}</strong> 路 ${escapeHtml(edge.state_family || "relation")}<br />
        鐢熸晥浣嶇疆锛氱 ${edge.valid_at_chapter || "-"} 绔?/ 娈佃惤 ${edge.valid_at_paragraph || "-"}<br />
        鐘舵€侊細${escapeHtml(edge.status || "unknown")}<br />
        ${escapeHtml(edge.fact || "褰撳墠娌℃湁鍙樉绀虹殑鍏崇郴璇存槑銆?)}
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
  if (!state.graphViewVisible) {
    renderGraphPanel();
    return;
  }
  await refreshKnowledgeGraph();
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
    container.innerHTML = '<p class="muted">褰撳墠绔犺妭杩樻病鏈夊彲鏄剧ず鐨勫唴瀹广€?/p>';
    return;
  }

  const page = document.createElement("article");
  page.className = "reading-page";
  page.innerHTML = `
    <header class="reading-page-header">
      <span>绗?${state.activeChapter} 绔?/span>
      <span>绗?${state.activePageIndex + 1} 椤?/span>
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
  setButtonLoading("character-generate-btn", true, "姝ｅ湪璇诲彇瑙掕壊鍊欓€?..");
  try {
    state.characterCandidates = await fetchJSON(
      `/api/books/${state.activeBook}/characters?current_chapter=${state.activeChapter}&limit=12`
    );
    renderCharacterCandidates();
  } catch (error) {
    state.characterCandidates = [];
    renderCharacterCandidates();
    document.getElementById("character-profile-card").innerHTML = `<p class="muted">瑙掕壊鍊欓€夎鍙栧け璐ワ細${error.message}</p>`;
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
      '<p class="muted">璇峰厛閫夋嫨涓€涓鑹诧紝鎴栨墜鍔ㄨ緭鍏ヨ鑹插悕鍚庡啀鐢熸垚鐢诲儚銆?/p>';
    return;
  }
  state.activeCharacterName = characterName;
  renderAssistantStatus();
  setButtonLoading("character-generate-btn", true, "姝ｅ湪鐢熸垚瑙掕壊鐢诲儚...");
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
    finishPendingWorkflow("done", "Character Profile Ready", "瑙掕壊鐢诲儚宸茬粡鐢熸垚锛屽彲浠ョ洿鎺ョ户缁鑹查櫔璇汇€?);
  } catch (error) {
    document.getElementById("character-profile-card").innerHTML = `<p class="muted">瑙掕壊鐢诲儚鐢熸垚澶辫触锛?{error.message}</p>`;
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
  if (state.graphViewVisible) {
    await refreshKnowledgeGraph();
  }
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
  state.graphViewData = null;
  state.graphViewError = "";
  state.graphSelection = null;
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
      `銆?{uploaded.book_title || uploaded.title}銆嬪凡缁忓畬鎴愮珷鑺傚垏鍒嗐€乪pisode 鏋勫缓涓?temporal graph 鍐欏叆銆俙
    );
  } catch (error) {
    pushConversation("assistant", `瀵煎叆澶辫触锛?{error.message}`);
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
  setButtonLoading("ask-btn", true, "姝ｅ湪鎬濊€?..");
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
        throw new Error("璇峰厛鐢熸垚鎴栭€夋嫨涓€涓鑹茬敾鍍忥紝鍐嶅彂璧疯鑹查櫔璇婚棶绛斻€?);
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
        ? "鍚嶅 agent 宸插畬鎴愬浘璋辨绱€乸ersona RAG 涓庨槻鍓ч€忚繃婊ゅ悗鐨勫洖绛斻€?
        : "瑙掕壊闄 agent 宸插畬鎴愬綋鍓嶅彲瑙佽寖鍥村唴鐨勮鑹插寲鍥炵瓟銆?
    );
  } catch (error) {
    pushConversation("assistant", `闂瓟澶辫触锛?{error.message}`);
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
  setButtonLoading("summary-btn", true, "姝ｅ湪鐢熸垚鎬荤粨...");
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
    finishPendingWorkflow("done", "Chapter Summary Ready", "褰撳墠绔犺妭鎬荤粨宸茬粡鍩轰簬宸茶 episode 涓庢椂搴忓浘鐘舵€佺敓鎴愬畬鎴愩€?);
  } catch (error) {
    pushConversation("assistant", `绔犺妭鎬荤粨澶辫触锛?{error.message}`);
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

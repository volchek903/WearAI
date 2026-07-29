const state = {
  clientId: "",
  catalog: null,
  profile: null,
  section: "photo",
  activeMode: null,
  selectedMusicPreset: null,
  agentMessages: [],
  telegramUser: null,
  telegramMeta: null,
  stageAsset: null,
  stageProgressTimer: null,
  stageProgressValue: 0,
  stageContextKey: "",
  uploadPreviewUrls: [],
  stagePreviewUrl: "",
};

const sectionLabels = {
  photo: "Фото",
  video: "Видео",
  music: "Музыка",
  agent: "Агент",
  profile: "Профиль",
};

const sectionDescriptions = {
  photo: "Фото-модели и шаблонные сцены",
  video: "Видео-генерации и motion-сценарии",
  music: "Музыкальный конструктор ACE-Step",
  agent: "Диалог с WeaRai и работа с документами",
  profile: "Профиль Telegram и параметры Mini App",
};

const heroContent = {
  photo: {
    eyebrow: "WearAI Studio",
    title: "Фото-генерации в Telegram с акцентом на скорость, премиальный вид и понятный workflow.",
    description:
      "Выбирай режимы, загружай референсы и запускай визуальные сценарии в одном экране без лишних переходов.",
  },
  video: {
    eyebrow: "WearAI Motion",
    title: "Видео-сцены и motion-модели собраны в компактной Mini App студии.",
    description:
      "Оживляй фото, управляй движением по референсу и отслеживай выдачу прямо внутри Telegram.",
  },
  music: {
    eyebrow: "WearAI Music",
    title: "Музыкальный конструктор с тегами, структурой и текстовыми секциями под мобильный ритм.",
    description:
      "Собирай трек через короткие, понятные шаги и получай результат в том же интерфейсе без разрыва сценария.",
  },
  agent: {
    eyebrow: "WearAI Agent",
    title: "Чат с агентом, памятью и документами в одном вертикальном цикле общения.",
    description:
      "Переключай память, анализ, документы и веб-поиск, не выходя из Mini App и не теряя контекст диалога.",
  },
  profile: {
    eyebrow: "WearAI Profile",
    title: "Компактный профиль с аватаром Telegram и текущим балансом кредитов.",
    description:
      "На экране профиля остаются только основные данные аккаунта и кошелек WearAI без технических блоков окружения.",
  },
};

const agentToggleLabels = {
  web_search_enabled: "Web search",
  documents_enabled: "Documents",
  memory_enabled: "Memory",
  deep_analysis_enabled: "Deep analysis",
  quick_mode_enabled: "Quick mode",
};

const els = {
  navButtons: [...document.querySelectorAll(".nav-btn")],
  brandHomeBtn: document.getElementById("brand-home-btn"),
  profileTrigger: document.getElementById("profile-trigger"),
  heroEyebrow: document.getElementById("hero-eyebrow"),
  heroTitle: document.getElementById("hero-title"),
  heroDescription: document.getElementById("hero-description"),
  headerAvatar: document.getElementById("header-avatar"),
  headerName: document.getElementById("header-name"),
  metricClient: document.getElementById("metric-client"),
  metricIdentity: document.getElementById("metric-identity"),
  metricContext: document.getElementById("metric-context"),
  metricModes: document.getElementById("metric-modes"),
  workspacePanel: document.getElementById("workspace-panel"),
  catalogPanel: document.getElementById("catalog-panel"),
  studioPanel: document.getElementById("studio-panel"),
  studioPanelHead: document.getElementById("studio-panel-head"),
  resultPanel: document.getElementById("result-panel"),
  profilePanel: document.getElementById("profile-panel"),
  profileAvatar: document.getElementById("profile-avatar"),
  profileName: document.getElementById("profile-name"),
  profileHandle: document.getElementById("profile-handle"),
  profileWallet: document.getElementById("profile-wallet"),
  modeGrid: document.getElementById("mode-grid"),
  modeCardTemplate: document.getElementById("mode-card-template"),
  catalogEyebrow: document.getElementById("catalog-eyebrow"),
  catalogTitle: document.getElementById("catalog-title"),
  catalogCount: document.getElementById("catalog-count"),
  studioTitle: document.getElementById("studio-title"),
  studioBadge: document.getElementById("studio-badge"),
  studioMeta: document.getElementById("studio-meta"),
  generationStage: document.getElementById("generation-stage"),
  stageMedia: document.getElementById("stage-media"),
  stageProgress: document.getElementById("stage-progress"),
  stageProgressLabel: document.getElementById("stage-progress-label"),
  stageProgressValue: document.getElementById("stage-progress-value"),
  stageProgressFill: document.getElementById("stage-progress-fill"),
  stageCaptionKicker: document.getElementById("stage-caption-kicker"),
  stageCaptionTitle: document.getElementById("stage-caption-title"),
  stageCaptionText: document.getElementById("stage-caption-text"),
  modeForm: document.getElementById("mode-form"),
  primaryFieldSlot: document.getElementById("primary-field-slot"),
  dynamicFields: document.getElementById("dynamic-fields"),
  uploadPreviewStrip: document.getElementById("upload-preview-strip"),
  uploadArea: document.getElementById("upload-area"),
  submitBtn: document.getElementById("submit-btn"),
  resultContent: document.getElementById("result-content"),
  resultStatus: document.getElementById("result-status"),
  musicPanel: document.getElementById("music-panel"),
  agentPanel: document.getElementById("agent-panel"),
  musicDuration: document.getElementById("music-duration"),
  musicSeed: document.getElementById("music-seed"),
  musicTags: document.getElementById("music-tags"),
  musicStructures: document.getElementById("music-structures"),
  musicSections: document.getElementById("music-sections"),
  musicSubmit: document.getElementById("music-submit"),
  agentMessages: document.getElementById("agent-messages"),
  agentForm: document.getElementById("agent-form"),
  agentInput: document.getElementById("agent-input"),
  agentSubmitBtn: document.getElementById("agent-submit-btn"),
  agentDocFile: document.getElementById("agent-doc-file"),
  agentDocMeta: document.getElementById("agent-doc-meta"),
  agentDocUploadBtn: document.getElementById("agent-doc-upload-btn"),
};

function getTelegramWebApp() {
  return window.Telegram?.WebApp || null;
}

function getTelegramUser() {
  return getTelegramWebApp()?.initDataUnsafe?.user || null;
}

function getTelegramMeta() {
  const tg = getTelegramWebApp();
  if (!tg) {
    return {
      platform: "browser",
      colorScheme: "dark",
      version: "preview",
      isExpanded: false,
      viewportHeight: null,
      chatType: "browser",
      startParam: "",
      hasInitData: false,
    };
  }

  return {
    platform: tg.platform || "telegram",
    colorScheme: tg.colorScheme || "dark",
    version: tg.version || "unknown",
    isExpanded: Boolean(tg.isExpanded),
    viewportHeight: Number.isFinite(tg.viewportHeight) ? Math.round(tg.viewportHeight) : null,
    chatType: tg.initDataUnsafe?.chat_type || "private",
    startParam: tg.initDataUnsafe?.start_param || "",
    hasInitData: Boolean(tg.initData),
  };
}

function getPreferredClientId() {
  const telegramUser = getTelegramUser();
  if (telegramUser?.id) {
    return `tg-${telegramUser.id}`;
  }
  return localStorage.getItem("wearai_client_id") || "";
}

function formatSessionLabel(clientId) {
  const raw = String(clientId || "").trim();
  if (!raw) return "ready";
  return raw.length <= 10 ? raw : `${raw.slice(0, 5)}...${raw.slice(-4)}`;
}

function getSectionFromHash() {
  const value = window.location.hash.replace(/^#/, "").trim();
  return sectionLabels[value] ? value : null;
}

function setSectionHash(section) {
  const nextHash = `#${section}`;
  if (window.location.hash === nextHash) return;
  window.history.replaceState(null, "", nextHash);
}

function getFullName(user) {
  if (!user) return "";
  return [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
}

function getDisplayName(user) {
  const fullName = getFullName(user);
  if (fullName) return fullName;
  if (user?.username) return `@${user.username}`;
  if (user?.id) return `User ${user.id}`;
  return "Web Preview";
}

function getProfileIdentity(user) {
  if (user?.username) return `@${user.username}`;
  if (user?.id) return `Telegram ID ${user.id}`;
  return "WearAI";
}

function getAvatarInitials(user) {
  const source = getFullName(user) || user?.username || "WearAI";
  const letters = source
    .replace(/^@/, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
  return letters || "WA";
}

function truncateMiddle(value, head = 22, tail = 12) {
  const text = String(value || "").trim();
  if (!text || text.length <= head + tail + 3) return text;
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

function formatMaybe(value, fallback = "Не передано") {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text || fallback;
}

function getAgentToggleInputs() {
  return [...document.querySelectorAll("[data-agent-toggle]")];
}

function formatBoolean(value) {
  if (value === true) return "Да";
  if (value === false) return "Нет";
  return "Не передано";
}

function getCurrentStageKey() {
  if (state.section === "music") return "music";
  if (!state.activeMode) return state.section;
  return `${state.section}:${state.activeMode.id}`;
}

function isPromptCandidate(field, index) {
  if (!field) return false;
  if (index === 0 && (field.type === "textarea" || field.type === "text")) return true;
  const name = String(field.name || "").toLowerCase();
  return (
    field.type === "textarea" ||
    name.includes("prompt") ||
    name.includes("text") ||
    name.includes("desc") ||
    name.includes("caption")
  );
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function revokeUploadPreviewUrls() {
  state.uploadPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.uploadPreviewUrls = [];
}

function revokeStagePreviewUrl() {
  if (state.stagePreviewUrl) {
    URL.revokeObjectURL(state.stagePreviewUrl);
    state.stagePreviewUrl = "";
  }
}

function countSelectedUploadFiles() {
  return [...els.uploadArea.querySelectorAll('input[type="file"]')].reduce(
    (count, input) => count + (input.files?.length || 0),
    0,
  );
}

function collectModeTextValues() {
  return [...els.modeForm.querySelectorAll("textarea[name], input[type='text'][name]")]
    .map((input) => ({
      label: input
        .closest(".field-group")
        ?.querySelector("label")
        ?.textContent?.trim() || input.name,
      value: input.value.trim(),
      placeholder: input.placeholder?.trim() || "",
    }))
    .filter((item) => item.value || item.placeholder);
}

function collectMusicNarrative() {
  const tags = [
    ...els.musicTags.querySelectorAll('input[type="checkbox"]:checked'),
  ].map((input) => input.parentElement?.textContent?.trim() || input.value);
  const sections = [...els.musicSections.querySelectorAll("textarea[name]")]
    .map((input) => input.value.trim())
    .filter(Boolean);

  if (sections.length) return sections.join(" / ");
  if (tags.length) return `Теги: ${tags.slice(0, 4).join(", ")}`;
  if (state.selectedMusicPreset?.label) return `Preset: ${state.selectedMusicPreset.label}`;
  return state.catalog?.music?.description || "Собери теги и структуру трека.";
}

function getStageIcon(section = state.section) {
  if (section === "video") return "video";
  if (section === "music") return "music";
  return "photo";
}

function isMinimalStageSection(section = state.section) {
  return section === "photo" || section === "video";
}

function formatModeKind(kind, fallbackSection = state.section) {
  const map = {
    photo_model: "Фото",
    photo_scenario: "Фото",
    video_model: "Видео",
    video_scenario: "Видео",
    music: "Музыка",
    agent: "Агент",
  };
  return map[kind] || sectionLabels[fallbackSection] || "WearAI";
}

function getStageSampleTitle() {
  if (state.section === "music") return state.catalog?.music?.title || "Music Preview";
  return state.activeMode?.title || "Preview";
}

function getStageSampleDescription() {
  if (state.section === "music") {
    return "Собери структуру, теги и текст секций. После генерации здесь появится готовый трек.";
  }
  return state.activeMode?.description || "Выбери режим и подготовь входные данные.";
}

function getStagePromptText() {
  if (state.section === "music") {
    return collectMusicNarrative();
  }

  const values = collectModeTextValues();
  const nonEmpty = values.filter((item) => item.value);
  if (nonEmpty.length) {
    return nonEmpty
      .map((item) => `${item.label}: ${item.value}`)
      .join(" / ");
  }
  if (values.length) {
    return values[0].placeholder || getStageSampleDescription();
  }

  const filesCount = countSelectedUploadFiles();
  if (filesCount > 0) {
    return `Файлы загружены: ${filesCount}. Добавь инструкции и запускай генерацию.`;
  }

  return getStageSampleDescription();
}

function updateStageCopy(options = {}) {
  if (isMinimalStageSection()) {
    els.stageCaptionKicker.textContent = "";
    els.stageCaptionTitle.textContent = "";
    els.stageCaptionText.textContent = "";
    return;
  }

  const {
    kicker = `${sectionLabels[state.section]} Preview`,
    title = getStageSampleTitle(),
    text = getStagePromptText(),
  } = options;

  els.stageCaptionKicker.textContent = kicker;
  els.stageCaptionTitle.textContent = title;
  els.stageCaptionText.textContent = text;
}

function renderStageSample(force = false) {
  const stageKey = getCurrentStageKey();
  if (!force && state.stageAsset && state.stageContextKey === stageKey) {
    updateStageCopy();
    return;
  }

  revokeStagePreviewUrl();
  state.stageAsset = null;
  state.stageContextKey = stageKey;

  const icon = getStageIcon();
  const primaryFileInput =
    state.section === "video"
      ? els.uploadArea.querySelector('input[name="video_file"]') ||
        els.uploadArea.querySelector('input[type="file"]')
      : els.uploadArea.querySelector('input[type="file"]');
  const primaryFile = primaryFileInput?.files?.[0] || null;
  let mediaHtml = `
    <div class="stage-window">
      <div class="stage-window__shell">
        <div class="stage-window__placeholder">
          <svg viewBox="0 0 24 24"><use href="#icon-${icon}"></use></svg>
        </div>
      </div>
    </div>
  `;

  if (primaryFile && isMinimalStageSection()) {
    state.stagePreviewUrl = URL.createObjectURL(primaryFile);
    if (state.section === "video" && primaryFile.type.startsWith("video/")) {
      mediaHtml = `
        <div class="stage-window">
          <div class="stage-window__shell">
            <div class="stage-window__media">
              <video src="${state.stagePreviewUrl}" muted playsinline preload="metadata"></video>
            </div>
            <div class="stage-window__play"></div>
          </div>
        </div>
      `;
    } else {
      mediaHtml = `
        <div class="stage-window">
          <div class="stage-window__shell">
            <div class="stage-window__media">
              <img src="${state.stagePreviewUrl}" alt="Preview" loading="lazy" />
            </div>
            ${state.section === "video" ? '<div class="stage-window__play"></div>' : ""}
          </div>
        </div>
      `;
    }
  } else if (state.section === "video") {
    mediaHtml = `
      <div class="stage-window">
        <div class="stage-window__shell">
          <div class="stage-window__placeholder">
            <svg viewBox="0 0 24 24"><use href="#icon-video"></use></svg>
          </div>
          <div class="stage-window__play"></div>
        </div>
      </div>
    `;
  } else if (state.section === "music") {
    mediaHtml = `
      <div class="stage-audio">
        <div class="stage-audio__card">
          <div class="stage-audio__bars">
            <span></span><span></span><span></span><span></span><span></span><span></span>
          </div>
          <strong>${escapeHtml(getStageSampleTitle())}</strong>
          <p>${escapeHtml(getStagePromptText())}</p>
        </div>
      </div>
    `;
  }

  els.stageMedia.className = `stage-media stage-media--sample stage-media--${state.section}`;
  els.stageMedia.innerHTML = `
    <div class="stage-media__badge">
      <svg viewBox="0 0 24 24"><use href="#icon-${icon}"></use></svg>
      <span>${escapeHtml(sectionLabels[state.section])}</span>
    </div>
    <div class="stage-sample">${mediaHtml}</div>
  `;

  updateStageCopy();
}

function renderStageAsset(asset) {
  if (!asset) return;

  revokeStagePreviewUrl();
  state.stageAsset = asset;
  state.stageContextKey = getCurrentStageKey();

  els.stageMedia.className = `stage-media stage-media--asset stage-media--${asset.kind}`;

  if (asset.kind === "image") {
    els.stageMedia.innerHTML = `
      <div class="stage-media__badge">
        <svg viewBox="0 0 24 24"><use href="#icon-photo"></use></svg>
        <span>Latest Result</span>
      </div>
      <img src="${asset.url}" alt="${escapeHtml(asset.filename)}" loading="lazy" />
    `;
  } else if (asset.kind === "video") {
    els.stageMedia.innerHTML = `
      <div class="stage-media__badge">
        <svg viewBox="0 0 24 24"><use href="#icon-video"></use></svg>
        <span>Latest Result</span>
      </div>
      <video src="${asset.url}" controls playsinline muted loop autoplay preload="metadata"></video>
    `;
  } else {
    els.stageMedia.innerHTML = `
      <div class="stage-media__badge">
        <svg viewBox="0 0 24 24"><use href="#icon-music"></use></svg>
        <span>Latest Result</span>
      </div>
      <div class="stage-audio">
        <div class="stage-audio__card">
          <div class="stage-audio__bars">
            <span></span><span></span><span></span><span></span><span></span><span></span>
          </div>
          <strong>${escapeHtml(asset.filename)}</strong>
          <p>Новый результат заменил sample и теперь закреплен в preview-stage.</p>
          <audio src="${asset.url}" controls preload="metadata"></audio>
        </div>
      </div>
    `;
  }

  updateStageCopy({
    kicker: "User Result",
    title: asset.filename,
    text: "Новый результат пользователя подставлен в preview-stage вместо sample кадра.",
  });
}

function startStageProgress(label) {
  stopStageProgress({ keepVisible: false });
  state.stageProgressValue = 6;
  els.stageProgressLabel.textContent = label;
  els.stageProgressValue.textContent = "6%";
  els.stageProgressFill.style.width = "6%";
  els.stageProgress.classList.remove("hidden");

  state.stageProgressTimer = window.setInterval(() => {
    state.stageProgressValue = Math.min(
      92,
      state.stageProgressValue + Math.max(1, (92 - state.stageProgressValue) * 0.12),
    );
    const rounded = Math.round(state.stageProgressValue);
    els.stageProgressValue.textContent = `${rounded}%`;
    els.stageProgressFill.style.width = `${rounded}%`;
  }, 240);
}

function completeStageProgress() {
  if (state.stageProgressTimer) {
    window.clearInterval(state.stageProgressTimer);
    state.stageProgressTimer = null;
  }

  els.stageProgressValue.textContent = "100%";
  els.stageProgressFill.style.width = "100%";

  window.setTimeout(() => {
    els.stageProgress.classList.add("hidden");
  }, 260);
}

function stopStageProgress(options = {}) {
  const { keepVisible = false } = options;
  if (state.stageProgressTimer) {
    window.clearInterval(state.stageProgressTimer);
    state.stageProgressTimer = null;
  }
  state.stageProgressValue = 0;
  if (!keepVisible) {
    els.stageProgress.classList.add("hidden");
    els.stageProgressFill.style.width = "0%";
    els.stageProgressValue.textContent = "0%";
  }
}

function bindStageInputListeners() {
  els.modeForm
    .querySelectorAll("textarea[name], input[type='text'][name], input[type='number'][name], select[name]")
    .forEach((input) => {
      const handler = () => {
        updateStageCopy();
        if (!state.stageAsset) renderStageSample();
      };
      input.addEventListener("input", handler);
      input.addEventListener("change", handler);
    });
}

function bindUploadPreviewListeners() {
  els.uploadArea.querySelectorAll('input[type="file"]').forEach((input) => {
    input.addEventListener("change", () => {
      renderUploadPreviewStrip();
      updateStageCopy();
      if (!state.stageAsset) renderStageSample(true);
    });
  });
}

function renderUploadPreviewStrip() {
  revokeUploadPreviewUrls();
  els.uploadPreviewStrip.innerHTML = "";

  const entries = [...els.uploadArea.querySelectorAll('input[type="file"]')].flatMap((input) => {
    const label =
      input.closest(".upload-card")?.querySelector("strong")?.textContent?.trim() || "Файл";
    return [...(input.files || [])].map((file) => ({ file, label }));
  });

  if (!entries.length) {
    els.uploadPreviewStrip.classList.add("hidden");
    return;
  }

  entries.slice(0, 6).forEach(({ file, label }) => {
    const card = document.createElement("article");
    card.className = "upload-preview-card";

    if (file.type.startsWith("image/")) {
      const url = URL.createObjectURL(file);
      state.uploadPreviewUrls.push(url);
      card.innerHTML = `
        <img src="${url}" alt="${escapeHtml(file.name)}" loading="lazy" />
        <footer>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(file.name)}</span>
        </footer>
      `;
    } else if (file.type.startsWith("video/")) {
      const url = URL.createObjectURL(file);
      state.uploadPreviewUrls.push(url);
      card.innerHTML = `
        <video src="${url}" muted playsinline preload="metadata"></video>
        <footer>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(file.name)}</span>
        </footer>
      `;
    } else {
      card.innerHTML = `
        <div class="upload-preview-card__empty">${escapeHtml(file.name)}</div>
        <footer>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(file.type || "document")}</span>
        </footer>
      `;
    }

    els.uploadPreviewStrip.append(card);
  });

  els.uploadPreviewStrip.classList.remove("hidden");
}

function isTelegramSession() {
  return Boolean(state.telegramUser?.id);
}

function renderAvatar(container, user) {
  if (!container) return;
  container.innerHTML = "";

  if (user?.photo_url) {
    const image = document.createElement("img");
    image.src = user.photo_url;
    image.alt = getDisplayName(user);
    image.loading = "lazy";
    container.append(image);
    return;
  }

  const fallback = document.createElement("span");
  fallback.className = "avatar__fallback";
  fallback.textContent = getAvatarInitials(user);
  container.append(fallback);
}

function renderDetails(container, rows) {
  container.innerHTML = "";

  rows.forEach((row) => {
    const wrapper = document.createElement("div");
    wrapper.className = "detail-row";

    const label = document.createElement("span");
    label.className = "detail-label";
    label.textContent = row.label;
    wrapper.append(label);

    let valueNode;
    if (row.href) {
      valueNode = document.createElement("a");
      valueNode.className = "detail-link";
      valueNode.href = row.href;
      valueNode.target = "_blank";
      valueNode.rel = "noreferrer";
    } else {
      valueNode = document.createElement("span");
      valueNode.className = "detail-value";
    }

    valueNode.textContent = row.value;
    if (row.mono) valueNode.classList.add("is-mono");
    wrapper.append(valueNode);

    container.append(wrapper);
  });
}

function renderStatusChips(container, chips) {
  container.innerHTML = "";
  chips.forEach((chip) => {
    const element = document.createElement("span");
    element.className = `status-chip ${chip.active ? "status-chip--on" : "status-chip--off"}`;
    element.textContent = chip.label;
    container.append(element);
  });
}

function renderMiniMetrics() {
  const metrics = [
    {
      icon: "wallet",
      label: "Баланс",
      value: String(state.profile?.balances?.total ?? 0),
      meta: "всего кредитов",
    },
    {
      icon: "gift",
      label: "Бесплатные",
      value: String(state.profile?.balances?.free ?? 0),
      meta: "free credits",
    },
  ];

  els.profileWallet.innerHTML = "";
  metrics.forEach((metric) => {
    const card = document.createElement("article");
    card.className = "mini-metric";
    card.innerHTML = `
      <span class="mini-metric__icon">
        <svg viewBox="0 0 24 24"><use href="#icon-${metric.icon}"></use></svg>
      </span>
      <span>${metric.label}</span>
      <strong>${metric.value}</strong>
      <small>${metric.meta}</small>
    `;
    els.profileWallet.append(card);
  });
}

function renderTelegramProfileView() {
  const user = state.telegramUser;

  renderAvatar(els.profileAvatar, user);

  els.profileName.textContent = getProfileIdentity(user);
  els.profileHandle.textContent = "";
  els.profileHandle.classList.add("hidden");

  renderMiniMetrics();
}

function updateHero(section) {
  const content = heroContent[section] || heroContent.photo;
  els.heroEyebrow.textContent = content.eyebrow;
  els.heroTitle.textContent = content.title;
  els.heroDescription.textContent = content.description;
}

function initTelegramMiniApp() {
  const tg = getTelegramWebApp();
  if (!tg) return;

  document.documentElement.classList.add("is-telegram-miniapp");

  try {
    tg.ready();
  } catch {}

  try {
    tg.expand();
  } catch {}

  try {
    tg.setHeaderColor?.("#05070d");
  } catch {}

  try {
    tg.setBackgroundColor?.("#05070d");
  } catch {}

  try {
    tg.setBottomBarColor?.("#05070d");
  } catch {}
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message =
      typeof payload === "string" ? payload : payload.detail || "Request failed";
    throw new Error(message);
  }

  return payload;
}

async function bootstrap() {
  initTelegramMiniApp();

  state.telegramUser = getTelegramUser();
  state.telegramMeta = getTelegramMeta();
  state.clientId = getPreferredClientId();

  const session = await api("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: state.clientId || null,
      username: state.telegramUser?.username || null,
    }),
  });

  state.clientId = session.client_id;
  state.profile = session;
  localStorage.setItem("wearai_client_id", state.clientId);

  state.catalog = await api("/api/catalog");
  const totalModes =
    state.catalog.photo_modes.length +
    state.catalog.video_modes.length +
    1 +
    1;

  els.metricModes.textContent = String(totalModes);

  renderProfile();
  bindEvents();
  hydrateMusicControlsAfterCatalog();
  renderEmptyState("Результат появится здесь", "Выбери режим, заполни форму и запусти генерацию.");
  syncAgentToggles();
  updateAgentDocMeta();

  const initialSection = getSectionFromHash() || "photo";
  switchSection(initialSection, { updateHash: !getSectionFromHash() });
}

function bindEvents() {
  els.brandHomeBtn.addEventListener("click", () => {
    switchSection("photo");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  els.profileTrigger.addEventListener("click", () => {
    switchSection("profile");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  els.navButtons.forEach((button) => {
    button.addEventListener("click", () => {
      switchSection(button.dataset.section);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  window.addEventListener("hashchange", () => {
    const section = getSectionFromHash();
    if (section && section !== state.section) {
      switchSection(section, { updateHash: false });
    }
  });

  getAgentToggleInputs().forEach((input) => {
    input.addEventListener("change", syncAgentToggleVisuals);
  });

  els.agentDocFile.addEventListener("change", () => {
    updateAgentDocMeta();
    if (els.agentDocFile.files?.length) {
      setAgentToggle("documents_enabled", true);
    }
  });

  els.musicDuration.addEventListener("change", () => {
    updateStageCopy();
    if (!state.stageAsset && state.section === "music") renderStageSample(true);
  });
  els.musicSeed.addEventListener("input", () => {
    updateStageCopy();
    if (!state.stageAsset && state.section === "music") renderStageSample();
  });

  els.modeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.activeMode) return;

    try {
      startStageProgress(state.section === "video" ? "Генерируем видео" : "Генерируем изображение");
      setBusy(true, "processing");
      if (state.section === "photo") {
        await submitMediaMode("/api/generate/photo");
      } else if (state.section === "video") {
        await submitMediaMode("/api/generate/video");
      }
      completeStageProgress();
    } catch (error) {
      stopStageProgress();
      showError(error.message);
    } finally {
      setBusy(false, "ready");
    }
  });

  els.musicSubmit.addEventListener("click", async () => {
    try {
      startStageProgress("Собираем и рендерим трек");
      setBusy(true, "music");
      const payload = collectMusicPayload();
      const response = await api("/api/generate/music", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applyResponse(response);
      completeStageProgress();
    } catch (error) {
      stopStageProgress();
      showError(error.message);
    } finally {
      setBusy(false, "ready");
    }
  });

  els.agentForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = els.agentInput.value.trim();
    if (!text) return;

    pushAgentBubble("user", text);
    els.agentInput.value = "";

    try {
      setBusy(true, "agent");
      const response = await api("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: state.clientId,
          text,
          toggles: collectAgentToggles(),
        }),
      });
      applyProfile(response.profile);
      pushAgentBubble("assistant", response.result.reply);
      els.resultStatus.textContent = "agent";
    } catch (error) {
      pushAgentBubble("assistant", `Ошибка: ${error.message}`);
    } finally {
      setBusy(false, "ready");
    }
  });

  els.agentDocUploadBtn.addEventListener("click", async () => {
    const file = els.agentDocFile.files?.[0];
    if (!file) return;

    try {
      setAgentToggle("documents_enabled", true);
      const formData = new FormData();
      formData.append("client_id", state.clientId);
      formData.append("file", file);
      const response = await api("/api/agent/documents", {
        method: "POST",
        body: formData,
      });
      pushAgentBubble(
        "assistant",
        `Документ загружен: ${response.result.file_name} (${response.result.text_length} символов)`,
      );
      els.agentDocFile.value = "";
      updateAgentDocMeta();
    } catch (error) {
      pushAgentBubble("assistant", `Ошибка загрузки документа: ${error.message}`);
    }
  });
}

function switchSection(section, options = {}) {
  const { updateHash = true } = options;
  if (!sectionLabels[section]) return;

  state.section = section;
  if (updateHash) setSectionHash(section);

  els.navButtons.forEach((button) =>
    button.classList.toggle("active", button.dataset.section === section),
  );
  els.profileTrigger.classList.toggle("active", section === "profile");

  updateHero(section);
  els.generationStage.classList.toggle("generation-stage--minimal", isMinimalStageSection(section));

  const isProfile = section === "profile";
  const isAgent = section === "agent";
  els.workspacePanel.classList.toggle("hidden", isProfile);
  els.workspacePanel.classList.toggle("workspace-panel--agent", isAgent);
  els.catalogPanel.classList.toggle("hidden", isAgent);
  els.resultPanel.classList.toggle("hidden", isAgent);
  els.studioPanelHead.classList.toggle("hidden", isAgent);
  els.studioPanel.classList.toggle("studio-panel--chat-only", isAgent);
  els.profilePanel.classList.toggle("hidden", !isProfile);

  if (isProfile) {
    renderTelegramProfileView();
    return;
  }

  els.catalogEyebrow.textContent = sectionLabels[section];
  els.catalogTitle.textContent = sectionDescriptions[section];
  els.studioBadge.textContent = sectionLabels[section];

  if (section === "music") {
    state.stageAsset = null;
    els.generationStage.classList.remove("hidden");
    els.modeForm.classList.add("hidden");
    els.agentPanel.classList.add("hidden");
    els.musicPanel.classList.remove("hidden");
    renderMusicCatalogCard();
    renderStageSample(true);
    return;
  }

  if (section === "agent") {
    els.generationStage.classList.add("hidden");
    els.modeForm.classList.add("hidden");
    els.musicPanel.classList.add("hidden");
    els.agentPanel.classList.remove("hidden");
    els.studioMeta.classList.add("hidden");
    els.studioMeta.innerHTML = "";
    ensureAgentIntro();
    return;
  }

  els.generationStage.classList.remove("hidden");
  els.musicPanel.classList.add("hidden");
  els.agentPanel.classList.add("hidden");
  els.modeForm.classList.remove("hidden");

  const items =
    section === "photo" ? state.catalog.photo_modes : state.catalog.video_modes;

  renderModeGrid(items);
  if (!state.activeMode || !items.find((item) => item.id === state.activeMode.id)) {
    selectMode(items[0]);
  } else {
    selectMode(state.activeMode);
  }
}

function renderModeGrid(items) {
  els.modeGrid.innerHTML = "";
  els.catalogCount.textContent = String(items.length);

  items.forEach((item) => {
    const fragment = els.modeCardTemplate.content.cloneNode(true);
    const root = fragment.querySelector(".mode-card");

    root.querySelector(".mode-kind").textContent = formatModeKind(item.kind, state.section);
    root.querySelector(".mode-title").textContent = item.title;
    root.classList.toggle("active", state.activeMode?.id === item.id);
    root.addEventListener("click", () => selectMode(item));

    els.modeGrid.append(root);
  });
}

function renderMusicCatalogCard() {
  els.catalogCount.textContent = "1";
  els.modeGrid.innerHTML = `
    <article class="mode-card active">
      <span class="mode-kind">Музыка</span>
      <div class="mode-card__head">
        <strong>${state.catalog.music.title}</strong>
        <span class="mode-card__dot"></span>
      </div>
    </article>
  `;

  els.studioTitle.textContent = "ACE-Step Music";
  els.studioBadge.textContent = "Музыка";
  els.studioMeta.classList.remove("hidden");
  els.studioMeta.innerHTML = `
    <div><span>Длительности</span><strong>${state.catalog.music.duration_options.join(", ")} сек</strong></div>
    <div><span>Пресеты</span><strong>${state.catalog.music.preset_structures.length} музыкальных схем</strong></div>
  `;
  updateStageCopy();
}

function selectMode(mode) {
  state.activeMode = mode;
  state.stageAsset = null;
  state.stageContextKey = "";

  renderModeGrid(
    state.section === "photo" ? state.catalog.photo_modes : state.catalog.video_modes,
  );

  els.studioTitle.textContent = mode.title;
  els.studioBadge.textContent = formatModeKind(mode.kind, state.section);
  els.studioMeta.classList.add("hidden");
  els.studioMeta.innerHTML = "";

  renderDynamicForm(mode);
}

function renderDynamicForm(mode) {
  revokeUploadPreviewUrls();
  els.primaryFieldSlot.innerHTML = "";
  els.dynamicFields.innerHTML = "";
  els.uploadPreviewStrip.innerHTML = "";
  els.uploadPreviewStrip.classList.add("hidden");
  els.uploadArea.innerHTML = "";

  const primaryFieldIndex = mode.fields.findIndex((field, index) =>
    isPromptCandidate(field, index),
  );

  mode.fields.forEach((field, index) => {
    const group = document.createElement("div");
    group.className = `field-group ${index === primaryFieldIndex ? "field-group--prompt" : ""}`.trim();

    const label = document.createElement("label");
    label.textContent = field.label;
    group.append(label);

    let input;
    if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = 5;
    } else if (field.type === "select") {
      input = document.createElement("select");
      field.options.forEach((option) => {
        const element = document.createElement("option");
        element.value = option.value;
        element.textContent = option.label;
        if (field.default === option.value) element.selected = true;
        input.append(element);
      });
    } else {
      input = document.createElement("input");
      input.type = field.type === "number" ? "number" : "text";
      if (field.min !== undefined) input.min = String(field.min);
      if (field.max !== undefined) input.max = String(field.max);
      if (field.default !== undefined && field.default !== null) {
        input.value = String(field.default);
      }
    }

    input.name = field.name;
    if (field.placeholder) input.placeholder = field.placeholder;
    if (field.required) input.required = true;
    group.append(input);

    if (field.help_text) {
      const help = document.createElement("small");
      help.className = "help-text";
      help.textContent = field.help_text;
      group.append(help);
    }

    if (index === primaryFieldIndex) {
      els.primaryFieldSlot.append(group);
    } else {
      els.dynamicFields.append(group);
    }
  });

  renderUploadInputs(mode);
  bindStageInputListeners();
  bindUploadPreviewListeners();
  renderUploadPreviewStrip();
  renderStageSample(true);
}

function renderUploadInputs(mode) {
  if (state.section === "photo") {
    if (mode.max_files > 0) {
      const card = createUploadCard(
        "media_files",
        "Загрузи изображения",
        `Допустимо: ${mode.min_files}-${mode.max_files} файлов`,
        "image/*",
        mode.max_files > 1,
      );
      els.uploadArea.append(card);
    }
    return;
  }

  if (mode.id === "animate_photo") {
    els.uploadArea.append(
      createUploadCard(
        "image_file",
        "Исходное фото",
        "Одно изображение для быстрой анимации",
        "image/*",
        false,
      ),
    );
    return;
  }

  if (mode.id === "motion_control") {
    els.uploadArea.append(
      createUploadCard("photo_file", "Фото", "Исходное фото", "image/*", false),
      createUploadCard(
        "video_file",
        "Видео-референс",
        "Обычное видео из галереи или камеры",
        "video/*",
        false,
      ),
    );

    const durationGroup = document.createElement("div");
    durationGroup.className = "field-group";
    durationGroup.innerHTML = `
      <label>Длительность видео-референса (сек)</label>
      <input name="video_duration_s" type="number" min="3" max="30" value="5" required />
      <small class="help-text">Если браузер не смог определить длительность автоматически, укажи ее вручную.</small>
    `;
    els.dynamicFields.append(durationGroup);
    return;
  }

  els.uploadArea.append(
    createUploadCard(
      "video_images",
      "Изображения для видео",
      mode.max_files > 1
        ? "Первое фото будет стартовым кадром, второе можно использовать как финальный кадр."
        : "Одно изображение для запуска модели.",
      "image/*",
      mode.max_files > 1,
    ),
  );
}

function createUploadCard(name, title, hint, accept, multiple) {
  const wrapper = document.createElement("label");
  wrapper.className = "upload-card";
  wrapper.innerHTML = `<strong>${title}</strong><span>${hint}</span>`;

  const input = document.createElement("input");
  input.type = "file";
  input.name = name;
  input.accept = accept;
  input.multiple = multiple;
  wrapper.append(input);

  return wrapper;
}

async function submitMediaMode(endpoint) {
  const formData = new FormData();
  formData.append("client_id", state.clientId);
  formData.append("mode_id", state.activeMode.id);

  const fields = {};
  els.dynamicFields.querySelectorAll("[name]").forEach((input) => {
    fields[input.name] = input.value;
  });

  if (state.section === "photo") {
    const fileInput = els.uploadArea.querySelector('input[type="file"]');
    const files = [...(fileInput?.files || [])];
    files.forEach((file) => formData.append("files", file));
  } else if (state.activeMode.id === "animate_photo") {
    const file = els.uploadArea.querySelector('input[name="image_file"]')?.files?.[0];
    if (file) formData.append("files", file);
  } else if (state.activeMode.id === "motion_control") {
    const photo = els.uploadArea.querySelector('input[name="photo_file"]')?.files?.[0];
    const video = els.uploadArea.querySelector('input[name="video_file"]')?.files?.[0];
    if (photo) formData.append("files", photo);
    if (video) formData.append("files", video);
  } else {
    const fileInput = els.uploadArea.querySelector('input[type="file"]');
    const files = [...(fileInput?.files || [])];
    files.forEach((file) => formData.append("files", file));
  }

  formData.append("fields_json", JSON.stringify(fields));
  const response = await api(endpoint, { method: "POST", body: formData });
  applyResponse(response);
}

function applyResponse(response) {
  applyProfile(response.profile);
  const asset = response.result?.assets?.[0];
  if (asset) renderStageAsset(asset);
  renderResult(response.result);
}

function applyProfile(profile) {
  state.profile = profile;
  renderProfile();
  syncAgentToggles();
}

function renderProfile() {
  if (!state.profile) return;

  const user = state.telegramUser;

  els.headerName.textContent = getDisplayName(user);
  els.metricClient.textContent = user?.username
    ? `@${user.username}`
    : `session ${formatSessionLabel(state.clientId)}`;
  els.metricIdentity.textContent = getDisplayName(user);
  els.metricContext.textContent = isTelegramSession()
    ? "данные из Telegram"
    : "аккаунт готов";

  renderAvatar(els.headerAvatar, user);
  renderTelegramProfileView();
}

function renderResult(result) {
  els.resultStatus.textContent = result.kind;

  if (!result.assets?.length) {
    renderEmptyState("Результат пуст", "Провайдер не вернул файлов для этого запроса.");
    return;
  }

  els.resultContent.className = "result-content";
  els.resultContent.innerHTML = "";

  result.assets.forEach((asset) => {
    const card = document.createElement("article");
    card.className = "result-card";

    let media = "";
    if (asset.kind === "image") {
      media = `<img src="${asset.url}" alt="${asset.filename}" loading="lazy" />`;
    } else if (asset.kind === "video") {
      media = `<video src="${asset.url}" controls playsinline preload="metadata"></video>`;
    } else if (asset.kind === "audio") {
      media = `
        <div class="audio-wrap">
          <audio src="${asset.url}" controls preload="metadata"></audio>
        </div>
      `;
    }

    card.innerHTML = `
      ${media}
      <div class="media-meta">
        <span>${asset.filename}</span>
        <a href="${asset.url}" download>Скачать</a>
      </div>
    `;
    els.resultContent.append(card);
  });
}

function renderEmptyState(title, subtitle) {
  els.resultContent.className = "result-content empty-state";
  els.resultContent.innerHTML = `
    <div class="empty-state-copy">
      <strong>${title}</strong>
      <span>${subtitle}</span>
    </div>
  `;
}

function showError(message) {
  stopStageProgress();
  els.resultStatus.textContent = "error";
  renderEmptyState("Ошибка", message);
}

function setBusy(isBusy, label) {
  els.submitBtn.disabled = isBusy;
  els.musicSubmit.disabled = isBusy;
  els.agentSubmitBtn.disabled = isBusy;
  els.agentDocUploadBtn.disabled = isBusy;
  els.agentInput.disabled = isBusy;
  els.agentDocFile.disabled = isBusy;
  getAgentToggleInputs().forEach((input) => {
    input.disabled = isBusy;
  });
  syncAgentToggleVisuals();
  els.studioBadge.textContent = isBusy
    ? label
    : formatModeKind(state.activeMode?.kind, state.section);
}

function renderMusicTags() {
  const categories = state.catalog.music.tag_categories;
  els.musicTags.innerHTML = "";

  Object.entries(categories).forEach(([name, options]) => {
    const group = document.createElement("section");
    group.className = "tag-group";
    group.innerHTML = `<h4>${name}</h4><div class="tag-row"></div>`;

    const row = group.querySelector(".tag-row");
    options.forEach((option) => {
      const chip = document.createElement("label");
      chip.className = "tag-chip";
      chip.innerHTML = `<input type="checkbox" value="${option.value}" />${option.label}`;
      chip.querySelector("input").addEventListener("change", () => {
        updateStageCopy();
        if (!state.stageAsset && state.section === "music") renderStageSample(true);
      });
      row.append(chip);
    });

    els.musicTags.append(group);
  });
}

function renderMusicStructures() {
  els.musicStructures.innerHTML = "";

  state.catalog.music.preset_structures.forEach((preset, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `structure-chip ${index === 0 ? "active" : ""}`;
    chip.textContent = preset.label;

    if (index === 0) state.selectedMusicPreset = preset;

    chip.addEventListener("click", () => {
      state.selectedMusicPreset = preset;
      [...els.musicStructures.children].forEach((child) =>
        child.classList.toggle("active", child === chip),
      );
      renderMusicSections();
      updateStageCopy();
      if (!state.stageAsset && state.section === "music") renderStageSample(true);
    });

    els.musicStructures.append(chip);
  });
}

function renderMusicSections() {
  els.musicSections.innerHTML = "";
  if (!state.selectedMusicPreset) return;

  state.selectedMusicPreset.sections.forEach((section, index) => {
    const group = document.createElement("div");
    group.className = "field-group";
    const key = `section_${index + 1}`;
    group.innerHTML = `
      <label>${section}</label>
      <textarea name="${key}" placeholder="Текст для секции: ${section}"></textarea>
    `;
    group.querySelector("textarea").addEventListener("input", () => {
      updateStageCopy();
      if (!state.stageAsset && state.section === "music") renderStageSample();
    });
    els.musicSections.append(group);
  });
}

function collectMusicPayload() {
  const selectedTags = [
    ...els.musicTags.querySelectorAll('input[type="checkbox"]:checked'),
  ].map((input) => input.value);

  const sectionTextInputs = els.musicSections.querySelectorAll("textarea[name]");
  const sectionTexts = {};
  sectionTextInputs.forEach((input) => {
    sectionTexts[input.name] = input.value;
  });

  return {
    client_id: state.clientId,
    selected_tags: selectedTags,
    sections: state.selectedMusicPreset?.sections || [],
    section_texts: sectionTexts,
    instrumental: selectedTags.includes("instrumental"),
    duration: Number(els.musicDuration.value || 30),
    seed: Number(els.musicSeed.value || -1),
  };
}

function syncAgentToggles() {
  if (state.profile?.agent_settings) {
    getAgentToggleInputs().forEach((input) => {
      input.checked = Boolean(state.profile.agent_settings[input.dataset.agentToggle]);
    });
  }
  syncAgentToggleVisuals();
}

function collectAgentToggles() {
  const toggles = {};
  getAgentToggleInputs().forEach((input) => {
    toggles[input.dataset.agentToggle] = input.checked;
  });
  return toggles;
}

function syncAgentToggleVisuals() {
  getAgentToggleInputs().forEach((input) => {
    const label = input.closest(".toggle--agent");
    if (!label) return;
    label.classList.toggle("is-active", input.checked);
    label.classList.toggle("is-disabled", input.disabled);
  });
}

function setAgentToggle(name, value) {
  const input = document.querySelector(`[data-agent-toggle="${name}"]`);
  if (!input) return;
  input.checked = value;
  syncAgentToggleVisuals();
}

function updateAgentDocMeta() {
  const file = els.agentDocFile.files?.[0];
  if (!file) {
    els.agentDocMeta.textContent = "Добавь файл, чтобы агент увидел материалы.";
    return;
  }

  els.agentDocMeta.textContent = `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB`;
}

function ensureAgentIntro() {
  if (state.agentMessages.length > 0) return;
  pushAgentBubble(
    "assistant",
    "Чат готов. Включи модули над полем ввода, при необходимости загрузи документ и опиши задачу.",
  );
}

function pushAgentBubble(role, text) {
  state.agentMessages.push({ role, text });
  const bubble = document.createElement("article");
  bubble.className = `agent-bubble ${role}`;
  bubble.textContent = text;
  els.agentMessages.append(bubble);
  els.agentMessages.scrollTop = els.agentMessages.scrollHeight;
}

function hydrateMusicControlsAfterCatalog() {
  els.musicDuration.innerHTML = state.catalog.music.duration_options
    .map((value) => `<option value="${value}">${value} сек</option>`)
    .join("");

  renderMusicTags();
  renderMusicStructures();
  renderMusicSections();
}

bootstrap().catch((error) => {
  showError(`Bootstrap failed: ${error.message}`);
});

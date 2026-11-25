/* ============================================================
   Мозаика — клиентское приложение.
   Общается с сервером через fetch по нашему HTTP API.
   Пользовательские данные вставляются только через textContent,
   поэтому разметка из подписи или сообщения не исполняется.
   ============================================================ */

(function () {
  "use strict";

  const state = {
    user: null,
    view: "feed",
    feed: { offset: 0, limit: 12, total: 0, loading: false, loaded: false },
    profile: { username: null, offset: 0, total: 0, loading: false },
    chat: { username: null, timer: null, dialogsTimer: null, lastId: 0 },
    post: null,
  };

  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ утилиты
  function initials(name) {
    return String(name || "?")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((word) => word.charAt(0))
      .join("")
      .toUpperCase();
  }

  function formatTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const now = new Date();
    const time = date.toLocaleTimeString("ru-RU", {
      hour: "2-digit", minute: "2-digit",
    });
    if (date.toDateString() === now.toDateString()) return time;
    const day = date.toLocaleDateString("ru-RU", {
      day: "numeric", month: "short",
    });
    return day + ", " + time;
  }

  function toast(message, kind) {
    const node = document.createElement("div");
    node.className = "toast" + (kind ? " toast--" + kind : "");
    node.textContent = message;
    $("toasts").appendChild(node);
    window.setTimeout(() => node.remove(), 4200);
  }

  async function api(path, options) {
    const config = Object.assign({ credentials: "same-origin" }, options || {});
    if (config.json !== undefined) {
      config.method = config.method || "POST";
      config.body = JSON.stringify(config.json);
      config.headers = Object.assign(
        { "Content-Type": "application/json; charset=utf-8" },
        config.headers || {}
      );
      delete config.json;
    }
    const response = await fetch(path, config);
    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("Требуется вход");
    }
    let data = null;
    const type = response.headers.get("Content-Type") || "";
    if (response.status !== 204 && type.indexOf("application/json") !== -1) {
      data = await response.json().catch(() => null);
    }
    if (!response.ok) {
      throw new Error((data && data.error) || "Ошибка " + response.status);
    }
    return data;
  }

  // ------------------------------------------------------------ лента
  function renderPost(post) {
    const node = $("post-template").content.firstElementChild.cloneNode(true);
    node.dataset.postId = post.id;
    const image = node.querySelector(".card__media img");
    image.src = post.image_url;
    image.alt = post.caption || "Публикация " + post.author.display_name;

    const caption = node.querySelector(".card__caption");
    caption.textContent = post.caption;
    if (!post.caption) caption.classList.add("hidden");

    node.querySelector(".avatar").textContent = initials(post.author.display_name);
    node.querySelector(".card__author-name").textContent = post.author.display_name;

    const authorButton = node.querySelector(".card__author");
    authorButton.addEventListener("click", () => {
      navigate("#profile/" + encodeURIComponent(post.author.username));
    });

    const likeButton = node.querySelector(".like");
    likeButton.classList.toggle("is-liked", Boolean(post.liked));
    likeButton.setAttribute("aria-pressed", post.liked ? "true" : "false");
    likeButton.addEventListener("click", () => toggleLike(post, likeButton));

    node.querySelector(".comments-count").textContent = String(post.comments || 0);
    node.querySelector(".card__media").addEventListener("click", () => openPost(post.id));
    node.querySelector(".comments-link").addEventListener("click", () => openPost(post.id));

    node.querySelector(".like__count").textContent = String(post.likes);
    return node;
  }

  function updateLikeUI(postId, liked, likes) {
    document.querySelectorAll('[data-post-id="' + postId + '"]').forEach((node) => {
      const button = node.classList.contains("like") ? node : node.querySelector(".like");
      if (!button) return;
      button.classList.toggle("is-liked", liked);
      button.setAttribute("aria-pressed", liked ? "true" : "false");
      const count = button.querySelector(".like__count");
      if (count) count.textContent = String(likes);
    });
  }

  function updateCommentsCount(postId, count) {
    document.querySelectorAll('[data-post-id="' + postId + '"]').forEach((node) => {
      const badge = node.classList.contains("comments-link")
        ? node.querySelector(".comments-count")
        : node.querySelector(".comments-count");
      if (badge) badge.textContent = String(count);
    });
  }

  async function toggleLike(post, button) {
    button.disabled = true;
    try {
      const data = await api("/api/posts/" + post.id + "/like", { method: "POST" });
      post.liked = data.liked;
      post.likes = data.likes;
      updateLikeUI(post.id, data.liked, data.likes);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function loadFeed(reset) {
    if (state.feed.loading) return;
    state.feed.loading = true;
    const more = $("load-more");
    more.disabled = true;
    if (reset) {
      state.feed.offset = 0;
      $("feed").replaceChildren();
    }
    try {
      const data = await api(
        "/api/feed?limit=" + state.feed.limit + "&offset=" + state.feed.offset
      );
      const fragment = document.createDocumentFragment();
      data.posts.forEach((post) => fragment.appendChild(renderPost(post)));
      $("feed").appendChild(fragment);
      state.feed.offset += data.posts.length;
      state.feed.total = data.total;
      state.feed.loaded = true;
      $("feed-count").textContent = data.total
        ? "публикаций: " + data.total
        : "";
      $("feed-empty").classList.toggle("hidden", data.total !== 0);
      more.classList.toggle(
        "hidden",
        state.feed.offset >= state.feed.total || data.posts.length === 0
      );
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.feed.loading = false;
      more.disabled = false;
    }
  }

  // ------------------------------------------------------------ просмотр фото
  async function openPost(postId) {
    try {
      const data = await api("/api/posts/" + postId);
      const post = data.post;
      state.post = post;

      $("post-image").src = post.image_url;
      $("post-image").alt = post.caption || "Публикация";
      $("post-avatar").textContent = initials(post.author.display_name);
      $("post-author").textContent = post.author.display_name;
      $("post-date").textContent = formatTime(post.created_at);
      $("post-caption").textContent = post.caption;
      $("post-caption").classList.toggle("hidden", !post.caption);

      const like = $("post-like");
      like.dataset.postId = post.id;
      like.classList.toggle("is-liked", Boolean(post.liked));
      like.setAttribute("aria-pressed", post.liked ? "true" : "false");
      $("post-likes").textContent = String(post.likes);
      $("post-download").href = "/api/posts/" + post.id + "/download";
      $("post-delete").classList.toggle(
        "hidden", !state.user || post.author.id !== state.user.id);

      $("comments-list").replaceChildren();
      $("comments-empty").classList.add("hidden");
      $("comments-count").textContent = "";
      $("comment-input").value = "";

      const dialog = $("post-dialog");
      if (!dialog.open) dialog.showModal();
      await loadComments(post.id);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function loadComments(postId) {
    const data = await api("/api/posts/" + postId + "/comments");
    $("comments-list").replaceChildren();
    data.comments.forEach(appendComment);
    $("comments-empty").classList.toggle("hidden", data.comments.length > 0);
    $("comments-count").textContent = data.total ? "(" + data.total + ")" : "";
  }

  function appendComment(comment) {
    const node = $("comment-template").content.firstElementChild.cloneNode(true);
    node.querySelector(".avatar").textContent = initials(comment.author.display_name);
    node.querySelector(".comment__author").textContent = comment.author.display_name;
    node.querySelector(".comment__time").textContent = formatTime(comment.created_at);
    node.querySelector(".comment__text").textContent = comment.text;
    $("comments-list").appendChild(node);
    $("comments-empty").classList.add("hidden");
    const list = $("comments-list");
    list.scrollTop = list.scrollHeight;
  }

  async function deletePost() {
    if (!state.post) return;
    if (!window.confirm("Удалить публикацию? Это действие необратимо.")) return;
    const postId = state.post.id;
    try {
      await api("/api/posts/" + postId + "/delete", { method: "POST" });
      $("post-dialog").close();
      toast("Публикация удалена", "success");
      document.querySelectorAll('.card[data-post-id="' + postId + '"]')
        .forEach((card) => card.remove());
      if (state.view === "profile") {
        openProfile(state.profile.username);
      } else {
        loadFeed(true);
      }
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function sendComment(event) {
    event.preventDefault();
    const input = $("comment-input");
    const text = input.value.trim();
    if (!text || !state.post) return;
    try {
      const data = await api(
        "/api/posts/" + state.post.id + "/comments", { json: { text: text } });
      appendComment(data.comment);
      input.value = "";
      state.post.comments = (state.post.comments || 0) + 1;
      updateCommentsCount(state.post.id, state.post.comments);
      $("comments-count").textContent = "(" + state.post.comments + ")";
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ------------------------------------------------------------ профиль
  async function openProfile(username) {
    switchView("profile");
    state.profile.username = username;
    state.profile.offset = 0;
    $("profile-grid").replaceChildren();
    $("profile-empty").classList.add("hidden");
    $("profile-more").classList.add("hidden");
    $("profile-name").textContent = "Загрузка…";
    $("profile-username").textContent = "";
    $("profile-avatar").textContent = "";

    try {
      const data = await api(
        "/api/feed?limit=12&offset=0&author=" + encodeURIComponent(username)
      );
      const user = data.user;
      $("profile-name").textContent = user.display_name;
      $("profile-username").textContent = "@" + user.username;
      $("profile-avatar").textContent = initials(user.display_name);
      document.title = user.display_name + " — Мозаика";

      const fragment = document.createDocumentFragment();
      data.posts.forEach((post) => fragment.appendChild(renderPost(post)));
      $("profile-grid").appendChild(fragment);
      state.profile.offset = data.posts.length;
      state.profile.total = data.total;
      $("profile-empty").classList.toggle("hidden", data.total !== 0);
      $("profile-more").classList.toggle("hidden", data.posts.length === 0 ||
        state.profile.offset >= state.profile.total);

      const isMe = state.user && state.user.id === user.id;
      $("profile-write").classList.toggle("hidden", isMe);
      $("profile-write").onclick = () => {
        navigate("#messages/" + encodeURIComponent(user.username));
      };
    } catch (error) {
      toast(error.message, "error");
      navigate("#feed");
    }
  }

  async function loadProfileMore() {
    if (state.profile.loading) return;
    state.profile.loading = true;
    const button = $("profile-more");
    button.disabled = true;
    try {
      const data = await api(
        "/api/feed?limit=12&offset=" + state.profile.offset +
        "&author=" + encodeURIComponent(state.profile.username)
      );
      const fragment = document.createDocumentFragment();
      data.posts.forEach((post) => fragment.appendChild(renderPost(post)));
      $("profile-grid").appendChild(fragment);
      state.profile.offset += data.posts.length;
      button.classList.toggle("hidden", state.profile.offset >= state.profile.total ||
        data.posts.length === 0);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.profile.loading = false;
      button.disabled = false;
    }
  }

  // ------------------------------------------------------------ поиск
  let searchTimer = null;

  function setupSearch() {
    const input = $("search-input");
    const results = $("search-results");

    input.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      const query = input.value.trim();
      if (!query) {
        results.classList.add("hidden");
        results.replaceChildren();
        return;
      }
      searchTimer = window.setTimeout(() => runSearch(query), 250);
    });

    document.addEventListener("click", (event) => {
      if (!results.contains(event.target) && event.target !== input) {
        results.classList.add("hidden");
      }
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        results.classList.add("hidden");
        input.blur();
      }
    });
  }

  function searchSection(title) {
    const label = document.createElement("div");
    label.className = "search-section";
    label.textContent = title;
    return label;
  }

  function renderUserHit(user, results) {
    const node = $("search-hit-template").content.firstElementChild.cloneNode(true);
    node.querySelector(".avatar").textContent = initials(user.display_name);
    node.querySelector(".search-hit__name").textContent = user.display_name;
    node.querySelector(".search-hit__login").textContent = "@" + user.username;
    node.addEventListener("click", () => {
      results.classList.add("hidden");
      $("search-input").value = "";
      navigate("#profile/" + encodeURIComponent(user.username));
    });
    return node;
  }

  function renderPostHit(post, results) {
    const node = $("search-post-template").content.firstElementChild.cloneNode(true);
    const thumb = node.querySelector(".search-hit__thumb");
    thumb.src = post.image_url;
    thumb.alt = post.caption || "Публикация";
    node.querySelector(".search-hit__name").textContent = post.caption || "Без подписи";
    node.querySelector(".search-hit__login").textContent =
      post.author.display_name + " · @" + post.author.username;
    node.addEventListener("click", () => {
      results.classList.add("hidden");
      $("search-input").value = "";
      openPost(post.id);
    });
    return node;
  }

  async function runSearch(query) {
    const results = $("search-results");
    try {
      const data = await api("/api/search?q=" + encodeURIComponent(query));
      results.replaceChildren();
      if (!data.users.length && !data.posts.length) {
        const empty = document.createElement("div");
        empty.className = "search-hit";
        empty.textContent = "Ничего не нашли";
        results.appendChild(empty);
      }
      if (data.users.length) {
        results.appendChild(searchSection("Люди"));
        data.users.forEach((user) => results.appendChild(renderUserHit(user, results)));
      }
      if (data.posts.length) {
        results.appendChild(searchSection("Публикации"));
        data.posts.forEach((post) => results.appendChild(renderPostHit(post, results)));
      }
      results.classList.remove("hidden");
    } catch (error) {
      results.classList.add("hidden");
    }
  }

  // ------------------------------------------------------------ сообщения
  function updateUnreadBadge(total) {
    const badge = $("unread-badge");
    const value = Number(total) || 0;
    badge.textContent = String(value);
    badge.classList.toggle("hidden", value === 0);
  }

  async function loadDialogs() {
    try {
      const data = await api("/api/messages");
      updateUnreadBadge(data.unread_total);
      renderDialogs(data.dialogs);
      return data;
    } catch (error) {
      toast(error.message, "error");
      return null;
    }
  }

  function renderDialogs(dialogs) {
    const list = $("dialogs-list");
    list.replaceChildren();
    $("dialogs-empty").classList.toggle("hidden", dialogs.length !== 0);

    dialogs.forEach((dialog) => {
      const node = $("dialog-template").content.firstElementChild.cloneNode(true);
      const user = dialog.user;
      node.querySelector(".avatar").textContent = initials(user.display_name);
      node.querySelector(".dialog-item__name").textContent = user.display_name;
      node.querySelector(".dialog-item__last").textContent =
        (dialog.last_mine ? "Вы: " : "") + dialog.last_text;
      node.querySelector(".dialog-item__time").textContent = formatTime(dialog.last_at);
      const badge = node.querySelector(".dialog-item__unread");
      badge.textContent = String(dialog.unread);
      badge.classList.toggle("hidden", dialog.unread === 0);
      if (state.chat.username === user.username) {
        node.classList.add("is-active");
      }
      node.addEventListener("click", () => {
        navigate("#messages/" + encodeURIComponent(user.username));
      });
      list.appendChild(node);
    });
  }

  function renderMessage(message) {
    const node = $("message-template").content.firstElementChild.cloneNode(true);
    node.querySelector(".bubble__text").textContent = message.text;
    node.querySelector(".bubble__time").textContent = formatTime(message.created_at);
    node.classList.toggle("bubble--mine", Boolean(message.mine));
    return node;
  }

  function appendMessages(messages) {
    const container = $("chat-messages");
    const placeholder = $("chat-placeholder");
    if (placeholder) placeholder.remove();
    const fragment = document.createDocumentFragment();
    messages.forEach((message) => {
      fragment.appendChild(renderMessage(message));
      state.chat.lastId = Math.max(state.chat.lastId, message.id);
    });
    container.appendChild(fragment);
    container.scrollTop = container.scrollHeight;
  }

  async function openDialog(username) {
    state.chat.username = username;
    state.chat.lastId = 0;
    stopChatTimers();

    $("chat-messages").replaceChildren();
    $("chat-name").textContent = "Загрузка…";
    $("chat-login").textContent = "";
    $("chat-form").classList.add("hidden");

    try {
      const data = await api("/api/messages/" + encodeURIComponent(username));
      $("chat-name").textContent = data.user.display_name;
      $("chat-login").textContent = "@" + data.user.username;
      $("chat-form").classList.remove("hidden");
      if (data.messages.length) {
        appendMessages(data.messages);
      } else {
        const empty = document.createElement("p");
        empty.className = "empty empty--small";
        empty.id = "chat-placeholder";
        empty.textContent = "Сообщений пока нет. Напишите первым!";
        $("chat-messages").appendChild(empty);
      }
      state.chat.lastId = data.messages.length
        ? data.messages[data.messages.length - 1].id
        : 0;
      document.title = data.user.display_name + " — Мозаика";
      await api("/api/messages/" + encodeURIComponent(username) + "/read",
        { method: "POST" });
      updateUnreadBadge(data.unread_total);
      await loadDialogs();
      startChatTimers();
      $("chat-input").focus();
    } catch (error) {
      toast(error.message, "error");
      navigate("#messages");
    }
  }

  async function pollDialog() {
    const username = state.chat.username;
    if (!username || document.hidden) return;
    try {
      const data = await api(
        "/api/messages/" + encodeURIComponent(username) +
        "?after_id=" + state.chat.lastId
      );
      if (state.chat.username !== username) return;
      updateUnreadBadge(data.unread_total);
      if (data.messages.length) {
        appendMessages(data.messages);
        await api("/api/messages/" + encodeURIComponent(username) + "/read",
          { method: "POST" });
        loadDialogs();
      }
    } catch (error) {
      /* временная ошибка сети — попробуем на следующем тике */
    }
  }

  function startChatTimers() {
    stopChatTimers();
    state.chat.timer = window.setInterval(pollDialog, 3000);
    state.chat.dialogsTimer = window.setInterval(() => {
      if (!document.hidden && state.view === "messages") loadDialogs();
    }, 9000);
  }

  function stopChatTimers() {
    if (state.chat.timer) window.clearInterval(state.chat.timer);
    if (state.chat.dialogsTimer) window.clearInterval(state.chat.dialogsTimer);
    state.chat.timer = null;
    state.chat.dialogsTimer = null;
  }

  async function sendMessage(event) {
    event.preventDefault();
    const input = $("chat-input");
    const text = input.value.trim();
    if (!text || !state.chat.username) return;
    input.value = "";
    try {
      const data = await api(
        "/api/messages/" + encodeURIComponent(state.chat.username),
        { json: { text: text } }
      );
      appendMessages([data.message]);
      await loadDialogs();
    } catch (error) {
      toast(error.message, "error");
      input.value = text;
    }
  }

  // ------------------------------------------------------------ загрузка
  let selectedFile = null;

  function setupUpload() {
    const dialog = $("upload-dialog");
    const input = $("upload-file");
    const preview = $("upload-preview");
    const icon = $("dropzone-icon");
    const text = $("dropzone-text");
    const dropzone = $("dropzone");
    const form = $("upload-form");

    function showFile(file) {
      if (!file) return;
      if (!/^image\/(jpeg|png|gif|webp)$/.test(file.type)) {
        toast("Поддерживаются JPEG, PNG, GIF и WEBP", "error");
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        toast("Файл больше 5 МБ", "error");
        return;
      }
      selectedFile = file;
      preview.src = URL.createObjectURL(file);
      preview.classList.remove("hidden");
      icon.classList.add("hidden");
      text.textContent = file.name;
    }

    $("upload-open").addEventListener("click", () => {
      selectedFile = null;
      form.reset();
      preview.classList.add("hidden");
      preview.removeAttribute("src");
      icon.classList.remove("hidden");
      text.textContent = "Перетащите изображение сюда или нажмите, чтобы выбрать файл";
      dialog.showModal();
    });

    $("upload-cancel").addEventListener("click", () => dialog.close());

    input.addEventListener("change", () => showFile(input.files[0]));

    ["dragenter", "dragover"].forEach((name) => {
      dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((name) => {
      dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.remove("is-dragover");
      });
    });
    dropzone.addEventListener("drop", (event) => {
      if (event.dataTransfer.files.length) {
        showFile(event.dataTransfer.files[0]);
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!selectedFile) {
        toast("Сначала выберите изображение", "error");
        return;
      }
      const submit = $("upload-submit");
      submit.disabled = true;
      submit.textContent = "Публикуем…";

      const body = new FormData();
      body.append("image", selectedFile, selectedFile.name);
      body.append("caption", $("upload-caption").value.trim());

      try {
        await api("/api/posts", { method: "POST", body: body });
        dialog.close();
        toast("Опубликовано", "success");
        state.feed.loaded = false;
        await loadFeed(true);
        navigate("#feed");
      } catch (error) {
        toast(error.message, "error");
      } finally {
        submit.disabled = false;
        submit.textContent = "Опубликовать";
      }
    });
  }

  // ------------------------------------------------------------ навигация
  function switchView(name) {
    state.view = name;
    ["feed", "profile", "messages"].forEach((view) => {
      $(view + "-view").classList.toggle("hidden", view !== name);
    });
    document.querySelectorAll(".nav__item").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.view === name);
    });
    if (name !== "messages") stopChatTimers();
    if (name === "feed") document.title = "Мозаика — лента";
  }

  function navigate(hash) {
    if (window.location.hash === hash) {
      route();
    } else {
      window.location.hash = hash;
    }
  }

  function route() {
    const hash = window.location.hash || "#feed";
    if (hash.indexOf("#profile/") === 0) {
      const username = decodeURIComponent(hash.slice("#profile/".length));
      openProfile(username);
      return;
    }
    if (hash.indexOf("#messages") === 0) {
      const rest = hash.slice("#messages".length).replace(/^\//, "");
      const username = rest ? decodeURIComponent(rest) : null;
      switchView("messages");
      stopChatTimers();
      loadDialogs();
      if (username) {
        openDialog(username);
      } else {
        state.chat.username = null;
        $("chat-name").textContent = "Выберите собеседника";
        $("chat-login").textContent = "";
        $("chat-form").classList.add("hidden");
        $("chat-messages").replaceChildren();
        const placeholder = document.createElement("p");
        placeholder.className = "empty empty--small";
        placeholder.id = "chat-placeholder";
        placeholder.textContent =
          "Откройте диалог слева или найдите человека через поиск.";
        $("chat-messages").appendChild(placeholder);
      }
      return;
    }
    switchView("feed");
    if (!state.feed.loaded) {
      loadFeed(true);
    }
  }

  // ------------------------------------------------------------ запуск
  async function init() {
    let me;
    try {
      me = await api("/api/me");
    } catch (error) {
      return;
    }
    state.user = me.user;
    $("user-name").textContent = me.user.display_name;
    $("avatar").textContent = initials(me.user.display_name);

    setupSearch();
    setupUpload();

    document.querySelectorAll(".nav__item").forEach((item) => {
      item.addEventListener("click", () => {
        const view = item.dataset.view;
        if (view === "messages") navigate("#messages");
        else if (view === "profile") navigate("#profile/" + encodeURIComponent(state.user.username));
        else navigate("#feed");
      });
    });
    $("load-more").addEventListener("click", () => loadFeed(false));
    $("profile-more").addEventListener("click", loadProfileMore);
    $("chat-form").addEventListener("submit", sendMessage);

    $("post-close").addEventListener("click", () => $("post-dialog").close());
    $("post-dialog").addEventListener("click", (event) => {
      if (event.target === $("post-dialog")) $("post-dialog").close();
    });
    $("post-dialog").addEventListener("close", () => { state.post = null; });
    $("post-like").addEventListener("click", () => {
      if (!state.post) return;
      toggleLike(state.post, $("post-like"));
    });
    $("post-delete").addEventListener("click", deletePost);
    $("comment-form").addEventListener("submit", sendComment);
    $("logout").addEventListener("click", async () => {
      try {
        await api("/api/logout", { method: "POST" });
      } finally {
        window.location.href = "/login";
      }
    });

    window.addEventListener("hashchange", route);
    await route();
    window.setInterval(() => {
      if (!document.hidden) {
        loadDialogs().catch(() => {});
      }
    }, 7000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/* Страница входа и регистрации: обмен с сервером по нашему HTTP API. */

(function () {
  "use strict";

  const form = document.getElementById("auth-form");
  const title = document.getElementById("auth-title");
  const subtitle = document.getElementById("auth-subtitle");
  const errorBox = document.getElementById("auth-error");
  const submit = document.getElementById("auth-submit");
  const displayNameField = document.getElementById("display-name-field");
  const displayNameInput = document.getElementById("auth-display-name");
  const usernameInput = document.getElementById("auth-username");
  const passwordInput = document.getElementById("auth-password");
  const tabs = Array.from(document.querySelectorAll(".tabs__item"));

  let mode = "login";

  function setMode(next) {
    mode = next;
    tabs.forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.mode === mode);
    });
    const isLogin = mode === "login";
    title.textContent = isLogin ? "С возвращением" : "Создать аккаунт";
    subtitle.textContent = isLogin
      ? "Войдите, чтобы увидеть ленту."
      : "Придумайте логин — он будет виден другим пользователям.";
    submit.textContent = isLogin ? "Войти" : "Зарегистрироваться";
    displayNameField.classList.toggle("hidden", isLogin);
    passwordInput.autocomplete = isLogin ? "current-password" : "new-password";
    errorBox.textContent = "";
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => setMode(tab.dataset.mode));
  });

  function showError(message) {
    errorBox.textContent = message;
  }

  async function request(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      const message = data && data.error ? data.error : "Ошибка " + response.status;
      throw new Error(message);
    }
    return data;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.textContent = "";

    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    const displayName = displayNameInput.value.trim();

    if (!username || !password) {
      showError("Заполните логин и пароль.");
      return;
    }

    submit.disabled = true;
    submit.textContent = mode === "login" ? "Входим…" : "Создаём…";

    try {
      if (mode === "register") {
        await request("/api/register", {
          username: username,
          password: password,
          display_name: displayName || username,
        });
      }
      await request("/api/login", { username: username, password: password });
      window.location.href = "/";
    } catch (error) {
      showError(error.message);
      submit.disabled = false;
      submit.textContent = mode === "login" ? "Войти" : "Зарегистрироваться";
    }
  });

  // Если сессия уже есть — сразу в ленту.
  fetch("/api/me", { credentials: "same-origin" })
    .then((response) => {
      if (response.ok) {
        window.location.href = "/";
      }
    })
    .catch(() => {});
})();

function applySystemTheme() {
  const preference = document.body.dataset.themePreference || document.body.dataset.theme || "light";
  document.body.dataset.theme = preference === "system" ?
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") :
    preference;
  document.documentElement.style.colorScheme = document.body.dataset.theme;
}

document.addEventListener("DOMContentLoaded", () => {
  const feedbackModal = document.getElementById("fmisFeedbackModal");
  let modalConfirmAction = null;
  const modalDetails = {
    success: ["Success", "bi-check-lg"],
    error: ["Something needs attention", "bi-exclamation-lg"],
    danger: ["Something needs attention", "bi-exclamation-lg"],
    warning: ["Please check", "bi-exclamation-triangle"],
    confirm: ["Please confirm", "bi-question-lg"],
    info: ["Notice", "bi-info-lg"],
  };

  function closeFeedbackModal() {
    if (!feedbackModal) return;
    feedbackModal.hidden = true;
    feedbackModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    modalConfirmAction = null;
  }

  function openFeedbackModal(message, kind = "info", onConfirm = null) {
    if (!feedbackModal) return;
    const normalizedKind = modalDetails[kind] ? kind : "info";
    const [title, icon] = modalDetails[normalizedKind];
    feedbackModal.dataset.kind = normalizedKind;
    document.getElementById("fmisModalTitle").textContent = title;
    document.getElementById("fmisModalMessage").textContent = message;
    document.getElementById("fmisModalIcon").innerHTML = `<i class="bi ${icon}"></i>`;
    document.getElementById("fmisModalConfirm").textContent = normalizedKind === "confirm" ? "Confirm" : "OK";
    const cancelButton = document.getElementById("fmisModalCancel");
    cancelButton.hidden = normalizedKind !== "confirm";
    if (cancelButton.hidden) cancelButton.style.setProperty("display", "none", "important");
    else cancelButton.style.removeProperty("display");
    modalConfirmAction = onConfirm;
    feedbackModal.hidden = false;
    feedbackModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    document.getElementById("fmisModalConfirm").focus();
  }
  window.fmisFeedback = openFeedbackModal;
  feedbackModal?.querySelectorAll("[data-modal-close]").forEach((button) => button.addEventListener("click", closeFeedbackModal));
  document.getElementById("fmisModalConfirm")?.addEventListener("click", () => {
    const action = modalConfirmAction;
    closeFeedbackModal();
    if (action) action();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && feedbackModal && !feedbackModal.hidden) closeFeedbackModal();
  });
  document.querySelectorAll("form[data-confirm]").forEach((form) => form.addEventListener("submit", (event) => {
    if (form.dataset.confirmed === "true") return;
    event.preventDefault();
    openFeedbackModal(form.dataset.confirm, "confirm", () => {
      form.dataset.confirmed = "true";
      form.requestSubmit();
    });
  }));
  const queuedMessage = document.querySelector("#fmisMessageQueue [data-message]");
  if (queuedMessage) openFeedbackModal(queuedMessage.dataset.message, queuedMessage.dataset.kind || "info");
  document.querySelectorAll("main .alert").forEach((alert) => {
    if (alert.closest("form") || alert.hasAttribute("data-inline-validation")) {
      alert.hidden = false;
      return;
    }
    if (!queuedMessage && alert.textContent.trim()) {
      const kind = [...alert.classList].find((name) => name.startsWith("alert-"))?.replace("alert-", "") || "error";
      openFeedbackModal(alert.textContent.trim(), kind);
    }
    alert.hidden = true;
  });
  const sidebarToggle = document.getElementById("sidebarToggle");
  const notificationMenu = document.querySelector(".notification-menu");
  const isMobileNavigation = () => window.matchMedia("(max-width: 600px)").matches;
  const closeMobileNavigation = () => {
    document.body.classList.remove("nav-mobile-open");
    if (isMobileNavigation()) sidebarToggle?.setAttribute("aria-expanded", "false");
  };
  const closeNotifications = () => notificationMenu?.removeAttribute("open");
  if (!isMobileNavigation() && localStorage.getItem("fmis-nav-collapsed") === "true") {
    document.body.classList.add("nav-collapsed");
    sidebarToggle?.setAttribute("aria-expanded", "false");
  }
  sidebarToggle?.addEventListener("click", () => {
    if (isMobileNavigation()) {
      closeNotifications();
      const opened = document.body.classList.toggle("nav-mobile-open");
      sidebarToggle.setAttribute("aria-expanded", String(opened));
    } else {
      const collapsed = document.body.classList.toggle("nav-collapsed");
      localStorage.setItem("fmis-nav-collapsed", String(collapsed));
      sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    }
  });
  document.querySelectorAll(".sidebar nav a, .sidebar .brand").forEach((link) => link.addEventListener("click", closeMobileNavigation));
  document.querySelector("[data-notification-close]")?.addEventListener("click", closeNotifications);
  notificationMenu?.addEventListener("toggle", () => {
    if (notificationMenu.open) closeMobileNavigation();
  });
  document.addEventListener("pointerdown", (event) => {
    if (notificationMenu?.open && !notificationMenu.contains(event.target)) closeNotifications();
    if (isMobileNavigation() && document.body.classList.contains("nav-mobile-open") &&
        !event.target.closest(".sidebar") && !event.target.closest("#sidebarToggle")) {
      closeMobileNavigation();
    }
  });
  window.addEventListener("scroll", closeNotifications, { passive: true });
  document.addEventListener("scroll", closeNotifications, { passive: true, capture: true });
  window.addEventListener("resize", () => {
    closeMobileNavigation();
    closeNotifications();
    if (!isMobileNavigation()) {
      sidebarToggle?.setAttribute("aria-expanded", String(!document.body.classList.contains("nav-collapsed")));
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMobileNavigation();
      closeNotifications();
    }
  });
  const currentPath = window.location.pathname;
  const roleLabel = document.querySelector(".sidebar-user small")?.textContent.trim();
  if (roleLabel === "STAFF") document.querySelector(".sidebar")?.classList.add("staff-sidebar");
  document.querySelectorAll(".sidebar nav a").forEach((link) => {
    const linkPath = new URL(link.href).pathname;
    const isDashboard = linkPath.startsWith("/dashboard/") && currentPath.startsWith("/dashboard/");
    const isModule = !linkPath.startsWith("/dashboard/") && currentPath.startsWith(linkPath);
    if (isDashboard || isModule) link.classList.add("active");
  });
  document.querySelectorAll(".farmer-toolbar select").forEach((select) => {
    select.addEventListener("change", () => select.form.submit());
  });
  document.querySelectorAll('form input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="submit"]), form select, form textarea').forEach((field) => field.classList.add("form-control"));
  document.querySelectorAll('select[data-farmer-picker]').forEach((select) => {
    if (select.dataset.enhanced === "true") return;
    select.dataset.enhanced = "true";
    let options = [...select.options].filter((option) => option.value);
    select.required = false;
    select.classList.add("farmer-picker-source");
    const picker = document.createElement("div");
    picker.className = "farmer-picker";
    picker.innerHTML = `<div class="farmer-picker-control"><input type="text" autocomplete="off" placeholder="${select.dataset.searchPlaceholder || "Type to find a farmer..."}" aria-label="Find a farmer record"></div><div class="farmer-picker-list" role="listbox" hidden></div>`;
    select.insertAdjacentElement("afterend", picker);
    const input = picker.querySelector("input");
    const list = picker.querySelector(".farmer-picker-list");
    const selected = options.find((option) => option.value === select.value);
    if (selected) input.value = selected.textContent.trim();
    let requestSequence = 0;
    const renderOptions = async (queryOverride = null) => {
      const query = (queryOverride === null ? input.value : queryOverride).trim().toLowerCase();
      if (select.dataset.searchUrl) {
        const sequence = ++requestSequence;
        const response = await fetch(`${select.dataset.searchUrl}?q=${encodeURIComponent(query)}`, {headers: {"X-Requested-With": "XMLHttpRequest"}});
        const payload = await response.json();
        if (sequence !== requestSequence) return;
        const selectedValue = select.value;
        const selectedOption = options.find((option) => option.value === select.value);
        select.replaceChildren(new Option("---------", ""));
        options = (payload.results || []).map((item) => {
          const option = new Option(item.label, String(item.id), false, String(item.id) === selectedValue);
          select.add(option);
          return option;
        });
        if (selectedOption && !options.some((option) => option.value === selectedOption.value)) {
          select.add(selectedOption);
          options.push(selectedOption);
        }
      }
      const matches = options.filter((option) => option.textContent.toLowerCase().includes(query)).slice(0, 100);
      list.replaceChildren();
      matches.forEach((option) => {
        const choice = document.createElement("button");
        choice.type = "button";
        choice.className = "farmer-picker-option";
        choice.dataset.value = option.value;
        choice.textContent = option.textContent.trim();
        choice.setAttribute("role", "option");
        choice.setAttribute("aria-selected", String(option.value === select.value));
        choice.addEventListener("click", () => {
          select.value = option.value;
          input.value = option.textContent.trim();
          select.dispatchEvent(new Event("change", {
            bubbles: true
          }));
          list.hidden = true;
        });
        list.appendChild(choice);
      });
      if (!matches.length) {
        const empty = document.createElement("p");
        empty.className = "farmer-picker-empty";
        empty.textContent = "No matching farmer record found.";
        list.appendChild(empty);
      }
      list.hidden = false;
    };
    input.addEventListener("focus", () => renderOptions(""));
    input.addEventListener("input", () => {
      const selectedOption = options.find((option) => option.value === select.value);
      if (!selectedOption || input.value !== selectedOption.textContent.trim()) select.value = "";
      renderOptions();
    });
    document.addEventListener("click", (event) => {
      if (!picker.contains(event.target)) list.hidden = true;
    });
  });
  applySystemTheme();
  const systemThemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
  systemThemeQuery.addEventListener?.("change", () => {
    if (document.body.dataset.themePreference === "system") applySystemTheme();
  });
  document.querySelectorAll('input[name="theme"]').forEach((input) => input.addEventListener("change", () => {
    document.body.dataset.themePreference = input.value;
    applySystemTheme();
  }));
  const reportTemplates = document.querySelectorAll(".template-row");
  reportTemplates.forEach((row) => {
    row.classList.remove("selected");
    row.addEventListener("mouseenter", () => row.classList.add("selected"));
    row.addEventListener("mouseleave", () => {
      if (!row.dataset.selected) row.classList.remove("selected");
    });
    row.addEventListener("click", () => {
      reportTemplates.forEach((item) => {
        item.dataset.selected = "";
        item.classList.remove("selected");
      });
      row.dataset.selected = "true";
      row.classList.add("selected");
    });
  });
  document.querySelectorAll("[data-card-url]").forEach((card) => {
    const openCard = () => {
      if (card.dataset.cardUrl) window.location.href = card.dataset.cardUrl;
    };
    card.addEventListener("click", (event) => {
      if (event.target.closest("a,button,input,select,textarea,form,summary")) return;
      openCard();
    });
    card.addEventListener("keydown", (event) => {
      if (event.target !== card || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      openCard();
    });
  });
  document.querySelectorAll("[data-record-url]").forEach((row) => {
    const openRecord = () => {
      if (row.dataset.recordUrl) window.location.href = row.dataset.recordUrl;
    };
    row.addEventListener("click", (event) => {
      if (event.target.closest("a,button,input,select,textarea,form,details,summary")) return;
      openRecord();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openRecord();
    });
  });
});

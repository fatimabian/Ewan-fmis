function applyAccentColor(color) {
    const hex = color.replace("#", "");
    if (hex.length !== 6) return;
    const red = parseInt(hex.slice(0, 2), 16);
    const green = parseInt(hex.slice(2, 4), 16);
    const blue = parseInt(hex.slice(4, 6), 16);
    const brightness = (red * 299 + green * 587 + blue * 114) / 1000;
    document.documentElement.style.setProperty("--fmis-accent", color);
    document.documentElement.style.setProperty("--green", color);
    document.documentElement.style.setProperty("--fmis-accent-text", brightness > 165 ? "#14202e" : "#ffffff");
}

function applySystemTheme() {
    const preference = document.body.dataset.themePreference || document.body.dataset.theme || "light";
    document.body.dataset.theme = preference === "system"
        ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
        : preference;
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
    const isMobileNavigation = () => window.matchMedia("(max-width: 600px)").matches;
    if (!isMobileNavigation() && localStorage.getItem("fmis-nav-collapsed") === "true") {
        document.body.classList.add("nav-collapsed");
        sidebarToggle?.setAttribute("aria-expanded", "false");
    }
    sidebarToggle?.addEventListener("click", () => {
        if (isMobileNavigation()) {
            const opened = document.body.classList.toggle("nav-mobile-open");
            sidebarToggle.setAttribute("aria-expanded", String(opened));
        } else {
            const collapsed = document.body.classList.toggle("nav-collapsed");
            localStorage.setItem("fmis-nav-collapsed", String(collapsed));
            sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
        }
    });
    document.querySelectorAll(".sidebar nav a").forEach((link) => link.addEventListener("click", () => document.body.classList.remove("nav-mobile-open")));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") document.body.classList.remove("nav-mobile-open");
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
        const options = [...select.options].filter((option) => option.value);
        const wasRequired = select.required;
        select.required = false;
        select.classList.add("farmer-picker-source");
        const picker = document.createElement("div");
        picker.className = "farmer-picker";
        picker.innerHTML = `<div class="farmer-picker-control"><input type="text" autocomplete="off" placeholder="${select.dataset.searchPlaceholder || "Type to find a farmer..."}" aria-label="Find a farmer record"></div><div class="farmer-picker-list" role="listbox" hidden></div>`;
        select.insertAdjacentElement("afterend", picker);
        const input = picker.querySelector("input");
        const list = picker.querySelector(".farmer-picker-list");
        input.required = wasRequired;
        const selected = options.find((option) => option.value === select.value);
        if (selected) input.value = selected.textContent.trim();
        const renderOptions = (queryOverride = null) => {
            const query = (queryOverride === null ? input.value : queryOverride).trim().toLowerCase();
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
                    input.setCustomValidity("");
                    select.dispatchEvent(new Event("change", { bubbles: true }));
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
            input.setCustomValidity("");
            renderOptions();
        });
        select.form?.addEventListener("submit", (event) => {
            if (wasRequired && !select.value) {
                event.preventDefault();
                input.setCustomValidity("Choose a farmer from the database list.");
                input.reportValidity();
                renderOptions();
            }
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
    const savedAccent = getComputedStyle(document.documentElement).getPropertyValue("--fmis-accent").trim();
    if (savedAccent) applyAccentColor(savedAccent);
    document.querySelectorAll('input[name="primary_color"]').forEach((input) => input.addEventListener("change", () => applyAccentColor(input.value)));
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
    const passwordLink = document.querySelector('[data-password-modal], a[href*="password_change"]');
    if (passwordLink) {
        passwordLink.addEventListener("click", (event) => {
            event.preventDefault();
            if (document.getElementById("fmis-password-modal")) return;
            const csrfToken = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
            const modal = document.createElement("div");
            modal.id = "fmis-password-modal";
            modal.innerHTML = `<div class="fmis-modal-backdrop" data-close-password-modal></div><section class="fmis-password-dialog" role="dialog" aria-modal="true" aria-labelledby="password-modal-title"><button type="button" class="fmis-modal-close" aria-label="Close" data-close-password-modal>×</button><h2 id="password-modal-title">Change Password</h2><p>Choose a new secure password for your FMIS account.</p><form method="post" action="/settings/change-password/"><input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}"><label>Current password<input required type="password" name="old_password" autocomplete="current-password"></label><label>New password<input required type="password" name="new_password1" autocomplete="new-password"></label><label>Confirm new password<input required type="password" name="new_password2" autocomplete="new-password"></label><div class="fmis-modal-actions"><button type="button" class="btn btn-outline-secondary" data-close-password-modal>Cancel</button><button class="btn btn-success">Save New Password</button></div></form></section>`;
            const modalStyles = document.createElement("style");
            modalStyles.textContent = ".fmis-modal-backdrop{position:fixed;inset:0;background:#09152199;z-index:1000}.fmis-password-dialog{position:fixed;z-index:1001;top:50%;left:50%;transform:translate(-50%,-50%);width:min(460px,92vw);background:#fff;color:#16233b;border-radius:15px;padding:28px;box-shadow:0 20px 60px #0005}.fmis-password-dialog h2{font-size:23px;margin:0 0 7px}.fmis-password-dialog p{color:#64728a;margin:0 0 20px}.fmis-password-dialog form{display:grid;gap:14px}.fmis-password-dialog label{display:grid;gap:7px;font-weight:700;font-size:13px}.fmis-password-dialog input{border:1px solid #dce5ec;border-radius:8px;padding:11px;font:inherit}.fmis-modal-close{position:absolute;right:16px;top:12px;border:0;background:transparent;font-size:28px;color:#56657b}.fmis-modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:7px}";
            document.head.appendChild(modalStyles);
            document.body.appendChild(modal);
            modal.querySelectorAll("[data-close-password-modal]").forEach((button) => button.addEventListener("click", () => modal.remove()));
            const passwordForm = modal.querySelector("form");
            passwordForm.addEventListener("submit", async (submitEvent) => {
                submitEvent.preventDefault();
                passwordForm.querySelectorAll(".inline-form-error").forEach((error) => error.remove());
                passwordForm.querySelectorAll(".is-invalid").forEach((input) => input.classList.remove("is-invalid"));
                const response = await fetch(passwordForm.action, {
                    method: "POST",
                    body: new FormData(passwordForm),
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                const result = await response.json();
                if (result.ok) {
                    modal.remove();
                    openFeedbackModal(result.message, "success");
                    return;
                }
                Object.entries(result.errors || {}).forEach(([name, errors]) => {
                    const input = passwordForm.querySelector(`[name="${name}"]`);
                    const target = input?.closest("label") || passwordForm;
                    input?.classList.add("is-invalid");
                    const message = document.createElement("span");
                    message.className = "inline-form-error";
                    message.textContent = errors.join(" ");
                    target.appendChild(message);
                });
            });
            modal.querySelector('input[name="old_password"]').focus();
        });
    }
    document.querySelectorAll("[data-record-url]").forEach((row) => {
        const openRecord = () => {
            if (row.dataset.recordUrl) window.location.href = row.dataset.recordUrl;
        };
        row.addEventListener("click", (event) => {
            if (event.target.closest("a,button,input,select,textarea,form")) return;
            openRecord();
        });
        row.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            openRecord();
        });
    });
});

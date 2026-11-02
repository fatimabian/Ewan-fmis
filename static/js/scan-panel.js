// Shared Scan & Auto-Fill control: a button and an (i) tip that open the upload dialog.
// FARMER panels also read the photo in place, fill this page's form and flag unsure fields.
(() => {
  const panels = document.querySelectorAll("[data-scan-panel]");

  // Scanning from the parcel or commodity form opens a review screen, so what was already typed is lost.
  const hostFormIsDirty = (panel) => {
    const forms = [...document.querySelectorAll(".content form")].filter((form) => !panel.contains(form));
    const host = forms.sort((a, b) => b.elements.length - a.elements.length)[0];
    if (!host) return false;
    return [...host.elements].some((el) => {
      if (!el.name || ["hidden", "submit", "button", "file"].includes(el.type) || el.name === "csrfmiddlewaretoken") return false;
      if (el.type === "checkbox" || el.type === "radio") return el.checked !== el.defaultChecked;
      if (el.tagName === "SELECT") return [...el.options].some((option) => option.selected !== option.defaultSelected);
      return el.value !== el.defaultValue;
    });
  };

  panels.forEach((panel) => {
    const dialog = panel.querySelector("[data-scan-dialog]");
    const sendForm = dialog.querySelector("form");
    if (sendForm) {
      sendForm.addEventListener("submit", (event) => {
        if (hostFormIsDirty(panel) && !window.confirm("You have already typed in this form. Scanning opens a review screen and this form starts again, so what you typed will be cleared. Continue?")) {
          event.preventDefault();
        }
      });
    }
    const tipButton = panel.querySelector("[data-scan-tip]");
    const tip = panel.querySelector(".sg-tip");
    const open = () => (dialog.showModal ? dialog.showModal() : dialog.setAttribute("open", ""));
    const close = () => (dialog.close ? dialog.close() : dialog.removeAttribute("open"));
    panel.querySelector("[data-scan-open]").addEventListener("click", open);
    panel.querySelectorAll("[data-scan-close]").forEach((button) => button.addEventListener("click", close));
    // A click on the dimmed backdrop (the dialog element itself) also closes it.
    dialog.addEventListener("click", (event) => { if (event.target === dialog) close(); });

    const showTip = (visible) => {
      tip.hidden = !visible;
      tipButton.setAttribute("aria-expanded", String(visible));
    };
    tipButton.addEventListener("click", () => showTip(tip.hidden));
    tipButton.addEventListener("mouseenter", () => showTip(true));
    tipButton.addEventListener("mouseleave", () => showTip(false));
    tipButton.addEventListener("focus", () => showTip(true));
    tipButton.addEventListener("blur", () => showTip(false));
    tipButton.addEventListener("keydown", (event) => { if (event.key === "Escape") showTip(false); });
  });

  // File rows: a first photo row, "Add page" for more, a remove button on added rows, and rule checks
  // before anything is sent (the server checks again).
  const fileRules = (panel) => {
    const box = panel.querySelector("[data-scan-files]");
    const template = box.querySelector("[data-scan-row-template]");
    const add = box.querySelector("[data-scan-add]");
    const count = box.querySelector("[data-scan-count]");
    const max = Number(box.dataset.max);
    const maxBytes = Number(box.dataset.maxMb) * 1024 * 1024;
    const extensions = box.dataset.extensions.split(",");
    const status = panel.querySelector("[data-scan-status]");
    const rows = () => box.querySelectorAll("[data-scan-row]");
    const inputs = () => [...box.querySelectorAll("[data-scan-file]")];

    const refresh = () => {
      const all = rows();
      all.forEach((row, index) => {
        const input = row.querySelector("[data-scan-file]");
        input.setAttribute("aria-label", `Photo ${index + 1}`);
        const remove = row.querySelector("[data-scan-remove]");
        remove.hidden = index === 0 && all.length === 1;
        remove.setAttribute("aria-label", `Remove photo ${index + 1}`);
      });
      count.textContent = `${all.length} of ${max} photos`;
      add.disabled = all.length >= max;
      add.title = all.length >= max ? `A scan can have at most ${max} photos.` : "";
    };

    const check = (input) => {
      const file = input.files[0];
      if (!file) return true;
      const name = file.name.toLowerCase();
      if (!extensions.some((extension) => name.endsWith(extension))) {
        status.textContent = `${file.name} is not allowed. Use ${extensions.map((e) => e.slice(1).toUpperCase()).join(", ")}.`;
        status.classList.add("sg-error");
        input.value = "";
        return false;
      }
      if (file.size > maxBytes) {
        status.textContent = `${file.name} is ${(file.size / 1048576).toFixed(1)} MB. Each photo must be ${box.dataset.maxMb} MB or smaller.`;
        status.classList.add("sg-error");
        input.value = "";
        return false;
      }
      status.textContent = "";
      status.classList.remove("sg-error");
      return true;
    };

    box.addEventListener("change", (event) => { if (event.target.matches("[data-scan-file]")) check(event.target); });
    add.addEventListener("click", () => {
      if (rows().length >= max) return;
      box.insertBefore(template.content.cloneNode(true), box.querySelector(".sg-files-bar"));
      refresh();
      inputs().at(-1).focus();
    });
    box.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-scan-remove]");
      if (!remove) return;
      remove.closest("[data-scan-row]").remove();
      refresh();
    });
    refresh();
    return {chosen: () => inputs().flatMap((input) => [...input.files]), box};
  };

  panels.forEach((panel) => { panel.fileRules = fileRules(panel); });

  document.querySelectorAll('[data-scan-panel][data-scan-target="FARMER"]').forEach((panel) => {
    const box = panel.querySelector("[data-scan-url]");
    const run = panel.querySelector("[data-scan-run]");
    const status = panel.querySelector("[data-scan-status]");
    const summary = panel.querySelector("[data-scan-summary]");
    const dialog = panel.querySelector("[data-scan-dialog]");
    const uploadStep = panel.querySelector("[data-scan-upload]");
    const reviewStep = panel.querySelector("[data-scan-review]");
    const form = document.getElementById(panel.querySelector("[data-scan-form]").dataset.scanForm);
    if (!box || !run || !form || !reviewStep) return;
    const csrf = () => form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";

    const say = (message, isError = false) => {
      status.textContent = message;
      status.classList.toggle("sg-error", isError);
    };
    const closeDialog = () => (dialog.close ? dialog.close() : dialog.removeAttribute("open"));
    const element = (name) => {
      const field = form.elements[name];
      return field && (field.tagName ? field : field[0]);
    };
    const labelOf = (name) => {
      const el = element(name);
      const label = el && el.id ? form.querySelector(`label[for="${el.id}"]`) : null;
      return (label ? label.textContent : name.replace(/_/g, " ")).replace(/[*:]/g, "").trim();
    };
    const shown = (name, value) => {
      const el = element(name);
      if (el && el.tagName === "SELECT") return ([...el.options].find((option) => option.value === value) || {}).text || value;
      return value;
    };
    // A short built-in prefix (the phone field starts with "09") is not something staff typed.
    const current = (name) => {
      const el = element(name);
      const value = el ? (form.elements[name].value || "") : "";
      return el && value === el.defaultValue && value.length <= 2 ? "" : value;
    };

    const clearFlag = (el) => {
      const wrapper = el.closest(".sg-flag");
      if (!wrapper) return;
      wrapper.classList.remove("sg-flag");
      wrapper.querySelector(".sg-flag-note")?.remove();
    };
    const flag = (el) => {
      const wrapper = el.closest(".registration-field") || el.parentElement;
      if (!wrapper || wrapper.classList.contains("sg-flag")) return;
      wrapper.classList.add("sg-flag");
      const note = document.createElement("small");
      note.className = "sg-flag-note";
      note.textContent = el.value ? "Unsure reading. Check against the form." : "Could not be read. Enter it from the form.";
      wrapper.append(note);
      el.addEventListener("input", () => clearFlag(el), {once: true});
      el.addEventListener("change", () => clearFlag(el), {once: true});
    };
    const fill = (name, value) => {
      const field = form.elements[name];
      if (!field) return false;
      field.value = value;
      if (field.value !== value) return false;
      const target = field.tagName ? field : field[0];
      target.dispatchEvent(new Event("input", {bubbles: true}));
      target.dispatchEvent(new Event("change", {bubbles: true}));
      return true;
    };
    const log = (payload) => fetch(box.dataset.scanLogUrl, {
      method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrf()}, body: JSON.stringify(payload),
    }).catch(() => {});

    const backToUpload = () => { reviewStep.hidden = true; reviewStep.replaceChildren(); uploadStep.hidden = false; };
    dialog.addEventListener("close", backToUpload);

    // The scan never overwrites silently: each scanned value is shown next to what is already
    // in the form, and staff tick the ones to use. Empty fields start ticked; different ones do not.
    function review(result, photos) {
      const unsure = new Set(result.needs_review || []);
      const rows = Object.entries(result.fields).filter(([, value]) => value).map(([name, value]) => {
        const now = current(name);
        const enterable = Boolean(element(name));
        const state = !enterable ? "missing" : !now ? "empty" : now === value ? "same" : "differs";
        return {name, value, now, state, unsure: unsure.has(name)};
      });
      if (!rows.length) { say("Nothing readable was found on the photo.", true); return false; }

      const table = document.createElement("table");
      table.className = "sg-review-table";
      table.innerHTML = "<caption>Choose the scanned values to use. Your own typed values are kept unless you tick them.</caption><thead><tr><th>Use</th><th>Field</th><th>Now in the form</th><th>Scanned</th></tr></thead>";
      const body = document.createElement("tbody");
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.dataset.state = row.state;
        const use = document.createElement("input");
        use.type = "checkbox";
        use.name = row.name;
        use.checked = row.state === "empty" || row.state === "same";
        use.disabled = row.state === "missing" || row.state === "same";
        use.setAttribute("aria-label", `Use the scanned ${labelOf(row.name)}`);
        const cells = [use, labelOf(row.name), row.now ? shown(row.name, row.now) : "empty", shown(row.name, row.value)];
        cells.forEach((content, index) => {
          const td = document.createElement("td");
          if (content instanceof Node) td.append(content); else td.textContent = content;
          if (index === 2 && !row.now) td.className = "sg-muted";
          if (index === 3) {
            const note = {same: " (same)", differs: " (different from yours)", missing: " (cannot be entered)"}[row.state];
            if (note) { const small = document.createElement("small"); small.textContent = note; td.append(small); }
            if (row.unsure) { const small = document.createElement("small"); small.className = "sg-flag-note"; small.textContent = " Unsure reading"; td.append(small); }
          }
          tr.append(td);
        });
        body.append(tr);
      });
      table.append(body);

      const actions = document.createElement("div");
      actions.className = "sg-dialog-actions";
      const apply = document.createElement("button");
      apply.type = "button"; apply.className = "btn btn-success";
      const cancel = document.createElement("button");
      cancel.type = "button"; cancel.className = "btn btn-outline-secondary"; cancel.textContent = "Cancel, apply nothing";
      const tickAll = document.createElement("button");
      tickAll.type = "button"; tickAll.className = "btn btn-outline-success"; tickAll.textContent = "Tick all";
      const boxes = () => [...table.querySelectorAll("input[type=checkbox]:not(:disabled)")];
      const count = () => boxes().filter((box) => box.checked).length;
      const refresh = () => { apply.textContent = `Apply ${count()} selected`; };
      table.addEventListener("change", refresh);
      tickAll.addEventListener("click", () => { const all = boxes().every((b) => b.checked); boxes().forEach((b) => { b.checked = !all; }); tickAll.textContent = all ? "Tick all" : "Untick all"; refresh(); });
      refresh();

      cancel.addEventListener("click", () => {
        log({cancelled: true});
        summary.textContent = "No scanned value was applied.";
        summary.hidden = false;
        closeDialog();
      });
      apply.addEventListener("click", () => {
        const applied = [], kept = [], skipped = [];
        rows.forEach((row) => {
          const chosen = boxes().find((b) => b.name === row.name)?.checked;
          if (row.state === "same") { return; }
          if (chosen && fill(row.name, row.value)) { applied.push(row.name); if (row.unsure) flag(element(row.name)); }
          else if (row.state === "differs") kept.push(row.name);
          else skipped.push(row.name);
        });
        const flagged = applied.filter((name) => unsure.has(name)).length;
        summary.textContent = `Applied ${applied.length} scanned value${applied.length === 1 ? "" : "s"}.` +
          `${kept.length ? ` Kept ${kept.length} you had typed.` : ""}${skipped.length ? ` Skipped ${skipped.length}.` : ""}` +
          `${flagged ? ` ${flagged} highlighted for checking.` : ""} Compare every value with the paper form before you continue. No photo was stored.`;
        summary.hidden = false;
        log({applied, kept, skipped});
        closeDialog();
      });
      actions.append(apply, tickAll, cancel);
      reviewStep.replaceChildren(table, actions);
      uploadStep.hidden = true;
      reviewStep.hidden = false;
      return true;
    }

    run.addEventListener("click", async () => {
      const files = panel.fileRules.chosen();
      if (!files.length) { say("Choose or capture a photo of the RSBSA form first.", true); return; }
      const data = new FormData();
      files.forEach((file) => data.append("rsbsa_scan", file));
      data.append("csrfmiddlewaretoken", csrf());
      run.disabled = true;
      say("Reading the form. This can take a few seconds…");
      try {
        const response = await fetch(box.dataset.scanUrl, {method: "POST", body: data, headers: {Accept: "application/json"}});
        const result = await response.json();
        if (response.ok) {
          // Photos read today count against the shared daily limit.
          const left = Math.max(0, Number(panel.fileRules.box.dataset.left) - files.length);
          panel.fileRules.box.dataset.left = left;
          panel.querySelector("[data-scan-left-text]").textContent = `${left} left today`;
        }
        if (!response.ok) { say(result.error || "The form could not be read. Try a clearer photo.", true); return; }
        say("");
        review(result, files.length);
      } catch (error) {
        say("The form reader could not be reached. You can still fill in the registration by hand.", true);
      } finally {
        run.disabled = false;
      }
    });
  });
})();

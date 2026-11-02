// Shared Scan & Auto-Fill control: a button and an (i) tip that open the upload dialog.
// FARMER panels also read the photo in place, fill this page's form and flag unsure fields.
(() => {
  const panels = document.querySelectorAll("[data-scan-panel]");

  panels.forEach((panel) => {
    const dialog = panel.querySelector("[data-scan-dialog]");
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
    const form = document.getElementById(panel.querySelector("[data-scan-form]").dataset.scanForm);
    if (!box || !run || !form) return;

    const say = (message, isError = false) => {
      status.textContent = message;
      status.classList.toggle("sg-error", isError);
    };

    const clearFlag = (field) => {
      const wrapper = field.closest(".sg-flag");
      if (!wrapper) return;
      wrapper.classList.remove("sg-flag");
      wrapper.querySelector(".sg-flag-note")?.remove();
    };

    const flag = (field) => {
      const wrapper = field.closest(".registration-field") || field.parentElement;
      if (!wrapper || wrapper.classList.contains("sg-flag")) return;
      wrapper.classList.add("sg-flag");
      const note = document.createElement("small");
      note.className = "sg-flag-note";
      note.textContent = field.value ? "Unsure reading. Check against the form." : "Could not be read. Enter it from the form.";
      wrapper.append(note);
      field.addEventListener("input", () => clearFlag(field), {once: true});
      field.addEventListener("change", () => clearFlag(field), {once: true});
    };

    // Values a previous scan entered are cleared first, so nothing from an older photo survives.
    let previous = [];
    const clearPrevious = () => {
      previous.forEach((name) => {
        const field = form.elements[name];
        if (!field) return;
        field.value = "";
        // Let widgets such as the date picker refresh their display.
        const element = field.tagName ? field : field[0];
        element?.dispatchEvent(new Event("input", {bubbles: true}));
        element?.dispatchEvent(new Event("change", {bubbles: true}));
      });
      form.querySelectorAll(".sg-flag").forEach((wrapper) => {
        wrapper.classList.remove("sg-flag");
        wrapper.querySelector(".sg-flag-note")?.remove();
      });
      previous = [];
    };

    const fill = (name, value) => {
      const field = form.elements[name];
      if (!field || !value) return false;
      field.value = value;
      if (field.value !== value) return false;
      const target = field.tagName ? field : (field[0] || null);
      (target || form).dispatchEvent(new Event("input", {bubbles: true}));
      (target || form).dispatchEvent(new Event("change", {bubbles: true}));
      return true;
    };

    run.addEventListener("click", async () => {
      const files = panel.fileRules.chosen();
      if (!files.length) { say("Choose or capture a photo of the RSBSA form first.", true); return; }
      const token = form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
      const data = new FormData();
      files.forEach((file) => data.append("rsbsa_scan", file));
      data.append("csrfmiddlewaretoken", token);
      run.disabled = true;
      say("Reading the form. This can take a few seconds…");
      try {
        const response = await fetch(box.dataset.scanUrl, {method: "POST", body: data, headers: {Accept: "application/json"}});
        const result = await response.json();
        // Photos read today count against the shared daily limit.
        if (response.ok) {
          const left = Math.max(0, Number(panel.fileRules.box.dataset.left) - files.length);
          panel.fileRules.box.dataset.left = left;
          panel.querySelector("[data-scan-left-text]").textContent = `${left} left today`;
        }
        if (!response.ok) { say(result.error || "The form could not be read. Try a clearer photo.", true); return; }
        clearPrevious();
        let filled = 0;
        const skipped = [];
        Object.entries(result.fields).forEach(([name, value]) => {
          if (!value) return;
          if (fill(name, value)) { filled += 1; previous.push(name); } else skipped.push(name.replace(/_/g, " "));
        });
        (result.needs_review || []).forEach((name) => {
          const field = form.elements[name];
          const element = field && (field.tagName ? field : field[0]);
          if (element) flag(element);
        });
        const unsure = (result.needs_review || []).length;
        const notes = [...(result.warnings || [])];
        if (skipped.length) notes.push(`Could not enter: ${skipped.join(", ")}.`);
        // Success closes the dialog; the result is summarised under the button.
        summary.textContent = `Filled in ${filled} field${filled === 1 ? "" : "s"}. ${unsure ? `${unsure} highlighted for checking. ` : ""}Compare every value with the paper form before you continue. ${notes.join(" ")}`;
        summary.hidden = false;
        say("");
        dialog.close ? dialog.close() : dialog.removeAttribute("open");
      } catch (error) {
        say("The form reader could not be reached. You can still fill in the registration by hand.", true);
      } finally {
        run.disabled = false;
      }
    });
  });
})();

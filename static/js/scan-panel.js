// Shared Scan & Auto-Fill panel, inline mode: read the photo, fill this page's form, flag unsure fields.
(() => {
  document.querySelectorAll('[data-scan-panel][data-scan-target="FARMER"]').forEach((panel) => {
    const box = panel.querySelector("[data-scan-url]");
    const run = panel.querySelector("[data-scan-run]");
    const fileInput = panel.querySelector("[data-scan-file]");
    const status = panel.querySelector("[data-scan-status]");
    const form = document.getElementById(panel.querySelector("[data-scan-form]").dataset.scanForm);
    if (!box || !run || !fileInput || !form) return;

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
      const file = fileInput.files[0];
      if (!file) { say("Choose or capture a photo of the RSBSA form first.", true); return; }
      const token = form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
      const data = new FormData();
      data.append("rsbsa_scan", file);
      data.append("csrfmiddlewaretoken", token);
      run.disabled = true;
      say("Reading the form. This can take a few seconds…");
      try {
        const response = await fetch(box.dataset.scanUrl, {method: "POST", body: data, headers: {Accept: "application/json"}});
        const result = await response.json();
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
        say(`Filled in ${filled} field${filled === 1 ? "" : "s"}. ${unsure ? `${unsure} highlighted for checking. ` : ""}Compare every value with the paper form before you continue. ${notes.join(" ")}`);
      } catch (error) {
        say("The form reader could not be reached. You can still fill in the registration by hand.", true);
      } finally {
        run.disabled = false;
      }
    });
  });
})();

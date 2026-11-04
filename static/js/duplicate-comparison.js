(() => {
 const initialize = () => {
  const dialog = document.getElementById("duplicateComparison");
  if (!dialog || dialog.dataset.comparisonInitialized) return;
  dialog.dataset.comparisonInitialized = "true";
  const form = dialog.querySelector("form");
  const records = dialog.querySelector("[data-comparison-records]");
  const status = dialog.querySelector("[data-comparison-status]");
  const save = dialog.querySelector("[data-comparison-save]");
  let url = "", generation = 0, saving = false;
  const outcome = () => {
    const separate = form.elements.decision.value === "SEPARATE";
    save.textContent = separate ? "Confirm Separate Farmers" : form.elements.decision.value === "SAME" ? "Confirm Same Person" : "Save review";
    form.querySelector('label[for="duplicateJustification"]').textContent = separate ? "Why are these separate farmers?" : "Why did you choose this outcome?";
  };
  form.elements.decision.addEventListener("change", outcome);
  const say = (message, error = false) => { status.textContent = message; status.classList.toggle("is-error", error); };
  const fields = [["name", "Full name"], ["birth_date", "Birthdate"], ["sex", "Sex"], ["barangay", "Barangay"], ["address", "Address"], ["phone", "Phone number"], ["valid_id_type", "ID type"], ["valid_id_number", "ID number"], ["rsbsa_number", "RSBSA number"], ["registration_status", "Registration status"], ["registered", "Registered on"]];
  const close = () => { if (!saving) dialog.close(); };
  dialog.querySelectorAll("[data-comparison-close]").forEach(button => button.addEventListener("click", close));
  dialog.addEventListener("click", event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close(); } });
  dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
  dialog.addEventListener("close", () => { generation++; records.replaceChildren(); form.reset(); form.hidden = true; });
  document.querySelectorAll("[data-compare-pair]").forEach(button => button.addEventListener("click", async () => {
    const ticket = ++generation;
    url = button.dataset.comparePair;
    form.reset(); form.hidden = true; records.replaceChildren();
    dialog.querySelector("[data-comparison-context]").textContent = `${button.dataset.score}% similarity · ${button.dataset.reasons}`;
    say("Loading both records…"); dialog.showModal();
    try {
      const response = await fetch(url, {headers: {Accept: "application/json"}, cache: "no-store"});
      if (!response.ok) throw new Error("Both records could not be loaded. Close and try again.");
      const data = await response.json();
      if (ticket !== generation) return;
      const table = document.createElement("table");
      const head = table.createTHead().insertRow();
      ["Field", data.first, data.second].forEach(value => {
        const th = document.createElement("th"); th.scope = "col";
        if (typeof value === "string") th.textContent = value;
        else { th.textContent = `${value.id} · ${value.name}`; const link = document.createElement("a"); link.href = value.detail_url; link.target = "_blank"; link.rel = "noopener"; link.textContent = "Open full record ↗"; th.append(link); }
        head.append(th);
      });
      const body = table.createTBody();
      fields.forEach(([key, label]) => {
        const row = body.insertRow();
        const heading = document.createElement("th"); heading.scope = "row"; heading.textContent = label; row.append(heading);
        [data.first, data.second].forEach(record => { row.insertCell().textContent = record[key] || "Not recorded"; });
        row.classList.toggle("is-different", data.first[key] !== data.second[key]);
      });
      records.append(table); form.hidden = false;
      if (data.existing) { form.elements.decision.value = data.existing.decision; form.elements.justification.value = data.existing.justification; }
      outcome();
      say("Differences are highlighted. Review the information, then choose an outcome.");
    } catch (error) { if (ticket === generation) say(error.message, true); }
  }));
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (saving || !form.reportValidity()) return;
    saving = true; save.disabled = true; say("Saving review…");
    try {
      const response = await fetch(url, {method: "POST", body: new FormData(form), headers: {Accept: "application/json"}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The review could not be saved.");
      saving = false;
      form.reset();
      dialog.close();
      window.fmisRefreshResults?.();
    } catch (error) { say(error.message, true); }
    finally { saving = false; save.disabled = false; }
  });
 };
 document.addEventListener("fmis:results-updated", initialize);
 initialize();
})();

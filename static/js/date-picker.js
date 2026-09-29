(() => {
  const MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const DATE_LABEL = new Intl.DateTimeFormat("en-PH", {
    year: "numeric", month: "long", day: "numeric",
  });
  let openPicker = null;
  let pickerSequence = 0;

  function parseISO(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function toISO(date) {
    const year = String(date.getFullYear()).padStart(4, "0");
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function sameDay(left, right) {
    return Boolean(left && right) && toISO(left) === toISO(right);
  }

  function enhanceDateInput(input) {
    if (input.dataset.fmisCalendar === "ready" || input.disabled) return;
    input.dataset.fmisCalendar = "ready";
    const isRequired = input.required;
    input.required = false;
    input.setAttribute("aria-hidden", "true");

    const wrapper = document.createElement("div");
    wrapper.className = "fmis-date-field";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    input.classList.add("fmis-date-source");
    input.tabIndex = -1;

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "fmis-date-trigger";
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML = '<span class="fmis-date-trigger-text"></span><i class="bi bi-calendar3" aria-hidden="true"></i>';
    wrapper.appendChild(trigger);

    const panel = document.createElement("section");
    panel.className = "fmis-date-picker";
    pickerSequence += 1;
    panel.id = `fmisDatePicker${pickerSequence}`;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "false");
    panel.setAttribute("aria-label", "Choose a date");
    panel.hidden = true;
    document.body.appendChild(panel);
    trigger.setAttribute("aria-controls", panel.id);

    const header = document.createElement("div");
    header.className = "fmis-date-picker-head";
    const previous = document.createElement("button");
    previous.type = "button";
    previous.className = "fmis-date-nav";
    previous.setAttribute("aria-label", "Previous month");
    previous.innerHTML = '<i class="bi bi-chevron-left" aria-hidden="true"></i>';
    const monthSelect = document.createElement("select");
    monthSelect.setAttribute("aria-label", "Month");
    MONTHS.forEach((month, monthIndex) => {
      const option = document.createElement("option");
      option.value = String(monthIndex);
      option.textContent = month;
      monthSelect.appendChild(option);
    });
    const yearSelect = document.createElement("select");
    yearSelect.setAttribute("aria-label", "Year");
    const next = document.createElement("button");
    next.type = "button";
    next.className = "fmis-date-nav";
    next.setAttribute("aria-label", "Next month");
    next.innerHTML = '<i class="bi bi-chevron-right" aria-hidden="true"></i>';
    header.append(previous, monthSelect, yearSelect, next);

    const weekdayRow = document.createElement("div");
    weekdayRow.className = "fmis-date-weekdays";
    WEEKDAYS.forEach((weekday) => {
      const label = document.createElement("span");
      label.textContent = weekday;
      weekdayRow.appendChild(label);
    });
    const days = document.createElement("div");
    days.className = "fmis-date-days";
    const footer = document.createElement("div");
    footer.className = "fmis-date-picker-foot";
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "fmis-date-clear";
    clear.textContent = "Clear";
    clear.hidden = isRequired;
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "fmis-date-apply";
    apply.innerHTML = '<i class="bi bi-calendar-check" aria-hidden="true"></i> Choose date';
    footer.append(clear, apply);
    panel.append(header, weekdayRow, days, footer);

    const initial = parseISO(input.value);
    let selected = initial;
    let draft = initial;
    let view = initial ? new Date(initial) : new Date();
    const minimum = parseISO(input.min);
    const maximum = parseISO(input.max);

    const updateTrigger = () => {
      const text = trigger.querySelector(".fmis-date-trigger-text");
      const current = parseISO(input.value);
      text.textContent = current ? DATE_LABEL.format(current) : "Choose date";
      text.classList.toggle("is-placeholder", !current);
      trigger.setAttribute("aria-label", current ? `Selected date: ${DATE_LABEL.format(current)}. Change date` : "Choose date");
      trigger.removeAttribute("aria-invalid");
    };

    const populateYears = () => {
      const currentYear = new Date().getFullYear();
      const earliest = Math.min(minimum?.getFullYear() ?? 1900, view.getFullYear());
      const latest = Math.max(maximum?.getFullYear() ?? currentYear + 15, view.getFullYear());
      yearSelect.replaceChildren();
      for (let year = latest; year >= earliest; year -= 1) {
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        yearSelect.appendChild(option);
      }
    };

    const outsideRange = (date) => (minimum && date < minimum) || (maximum && date > maximum);

    const render = () => {
      populateYears();
      monthSelect.value = String(view.getMonth());
      yearSelect.value = String(view.getFullYear());
      days.replaceChildren();
      const firstWeekday = new Date(view.getFullYear(), view.getMonth(), 1).getDay();
      const daysInMonth = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
      for (let cell = 0; cell < 42; cell += 1) {
        const dayNumber = cell - firstWeekday + 1;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "fmis-date-day";
        if (dayNumber < 1 || dayNumber > daysInMonth) {
          button.classList.add("is-empty");
          button.tabIndex = -1;
        } else {
          const date = new Date(view.getFullYear(), view.getMonth(), dayNumber);
          button.textContent = String(dayNumber);
          button.setAttribute("aria-label", DATE_LABEL.format(date));
          button.disabled = Boolean(outsideRange(date));
          button.classList.toggle("is-today", sameDay(date, new Date()));
          button.classList.toggle("is-selected", sameDay(date, draft));
          button.addEventListener("click", () => {
            draft = date;
            render();
          });
        }
        days.appendChild(button);
      }
    };

    const positionPanel = () => {
      if (window.matchMedia("(max-width: 520px)").matches) return;
      const rect = trigger.getBoundingClientRect();
      const panelWidth = Math.min(360, window.innerWidth - 24);
      const left = Math.max(12, Math.min(rect.left, window.innerWidth - panelWidth - 12));
      const below = rect.bottom + 8;
      const panelHeight = panel.offsetHeight;
      const top = below + panelHeight <= window.innerHeight - 12
        ? below
        : Math.max(12, rect.top - panelHeight - 8);
      panel.style.left = `${left}px`;
      panel.style.top = `${top}px`;
    };

    const close = (returnFocus = false) => {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (openPicker?.panel === panel) openPicker = null;
      if (returnFocus) trigger.focus();
    };

    const open = () => {
      if (openPicker && openPicker.panel !== panel) openPicker.close();
      selected = parseISO(input.value);
      draft = selected;
      view = selected ? new Date(selected) : new Date();
      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      render();
      positionPanel();
      openPicker = { panel, wrapper, close, positionPanel };
      monthSelect.focus();
    };

    trigger.addEventListener("click", () => panel.hidden ? open() : close(true));
    previous.addEventListener("click", () => {
      view = new Date(view.getFullYear(), view.getMonth() - 1, 1);
      render();
    });
    next.addEventListener("click", () => {
      view = new Date(view.getFullYear(), view.getMonth() + 1, 1);
      render();
    });
    monthSelect.addEventListener("change", () => {
      view = new Date(view.getFullYear(), Number(monthSelect.value), 1);
      render();
    });
    yearSelect.addEventListener("change", () => {
      view = new Date(Number(yearSelect.value), view.getMonth(), 1);
      render();
    });
    apply.addEventListener("click", () => {
      if (!draft) return;
      input.value = toISO(draft);
      selected = draft;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      updateTrigger();
      close(true);
    });
    clear.addEventListener("click", () => {
      input.value = "";
      selected = null;
      draft = null;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      updateTrigger();
      close(true);
    });
    input.addEventListener("change", updateTrigger);
    input.form?.addEventListener("submit", (event) => {
      if (isRequired && !input.value) {
        event.preventDefault();
        trigger.setAttribute("aria-invalid", "true");
        trigger.focus();
        if (window.fmisFeedback) window.fmisFeedback("Please choose a date for the highlighted field.", "warning");
      }
    });
    updateTrigger();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('input[type="date"]:not([data-native-date])').forEach(enhanceDateInput);
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches('input[type="date"]:not([data-native-date])')) enhanceDateInput(node);
        node.querySelectorAll?.('input[type="date"]:not([data-native-date])').forEach(enhanceDateInput);
      }));
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  document.addEventListener("pointerdown", (event) => {
    if (!openPicker || openPicker.panel.contains(event.target) || openPicker.wrapper.contains(event.target)) return;
    openPicker.close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openPicker) openPicker.close(true);
  });
  window.addEventListener("resize", () => openPicker?.positionPanel());
  window.addEventListener("scroll", () => openPicker?.positionPanel(), true);
})();

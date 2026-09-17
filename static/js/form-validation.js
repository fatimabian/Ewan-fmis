document.addEventListener("DOMContentLoaded", () => {
  const controls = "input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea";
  const loadingOverlay = document.getElementById("fmisSubmitLoading");
  const loadingTitle = document.getElementById("fmisSubmitLoadingTitle");
  const mark = (field) => {
    field.classList.add("is-invalid");
    field.setAttribute("aria-invalid", "true");
  };
  const clear = (field) => {
    if (!field.validity || field.validity.valid) {
      field.classList.remove("is-invalid");
      field.removeAttribute("aria-invalid");
    }
  };
  const capitalizeFirst = (value) => {
    const index = value.search(/\p{L}/u);
    return index < 0 ? value : value.slice(0, index) + value[index].toUpperCase() + value.slice(index + 1);
  };

  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      form.classList.add("fmis-form-submitted");
      form.querySelectorAll(controls).forEach((field) => {
        if (field.validity && !field.validity.valid) mark(field);
      });

      const method = (form.getAttribute("method") || "get").toLowerCase();
      const hasOwnLoadingState = form.id === "rsbsaRegistration";
      const isDownload = form.id === "reportGenerator" || form.hasAttribute("data-download-form");
      if (
        event.defaultPrevented ||
        method !== "post" ||
        hasOwnLoadingState ||
        isDownload ||
        !form.checkValidity()
      ) {
        return;
      }

      const action = (form.getAttribute("action") || window.location.pathname).toLowerCase();
      const requestedMessage = form.dataset.loadingMessage;
      let message = requestedMessage || "Saving changes…";
      if (!requestedMessage && action.includes("logout")) message = "Signing out…";
      if (!requestedMessage && (action.includes("delete") || action.includes("deactivate"))) {
        message = "Updating record status…";
      }
      if (loadingTitle) loadingTitle.textContent = message;
      if (loadingOverlay) loadingOverlay.hidden = false;

      const submitButton = event.submitter;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.setAttribute("aria-busy", "true");
      }
    });
    form.querySelectorAll(controls).forEach((field) => {
      field.addEventListener("invalid", () => mark(field));
      field.addEventListener("input", () => clear(field));
      field.addEventListener("change", () => clear(field));
    });
  });

  document.querySelectorAll('input[name="phone_number"]').forEach((field) => {
    const enforcePrefix = () => {
      let digits = field.value.replace(/\D/g, "").slice(0, 11);
      if (!digits.startsWith("09")) {
        digits = "09" + digits.replace(/^0/, "").replace(/^9/, "");
        digits = digits.slice(0, 11);
      }
      field.value = digits;
    };
    const getInlineError = () => {
      const next = field.nextElementSibling;
      return next && next.classList.contains("inline-form-error") ? next : null;
    };
    const clearPhoneError = () => {
      field.classList.remove("is-invalid");
      field.removeAttribute("aria-invalid");
      getInlineError()?.remove();
    };
    const showPhoneError = (message) => {
      mark(field);
      let error = getInlineError();
      if (!error) {
        error = document.createElement("span");
        error.className = "inline-form-error";
        field.insertAdjacentElement("afterend", error);
      }
      error.textContent = message;
    };
    const validatePhone = () => {
      const digits = field.value.replace(/\D/g, "");
      if (!digits || digits === "09") {
        clearPhoneError();
        return;
      }
      if (digits.length !== 11 || !digits.startsWith("09")) {
        showPhoneError("Phone number must be 11 digits.");
      } else {
        clearPhoneError();
      }
    };
    if (!field.value) field.value = "09";
    field.addEventListener("input", () => {
      enforcePrefix();
      clearPhoneError();
    });
    field.addEventListener("blur", validatePhone);
    field.addEventListener("keydown", (e) => {
      const atLockedZone = field.selectionStart <= 2 && field.selectionEnd <= 2;
      if ((e.key === "Backspace" || e.key === "Delete") && atLockedZone) e.preventDefault();
    });
    field.addEventListener("focus", () => {
      if (field.selectionStart < 2) {
        const end = field.value.length;
        field.setSelectionRange(end, end);
      }
    });
  });

  document.querySelectorAll("[data-capitalize-first=true]").forEach((field) => {
    field.addEventListener("blur", () => {
      field.value = capitalizeFirst(field.value.trim());
    });
  });

  document.querySelectorAll('select[name="civil_status"]').forEach((civilStatus) => {
    const form = civilStatus.closest("form");
    const spouse = form?.querySelector('[name="spouse_name"]');
    if (!spouse) return;

    const syncSpouseRequirement = () => {
      const required = civilStatus.value === "MARRIED";
      spouse.required = required;
      spouse.toggleAttribute("aria-required", required);
      if (!required) {
        spouse.setCustomValidity("");
        clear(spouse);
      }

      const container = spouse.closest(".registration-field, .form-group");
      if (!container) return;
      let marker = [...container.children].find(
        (element) => element.tagName === "B" && element.textContent.trim() === "*"
      );
      if (required && !marker) {
        marker = document.createElement("b");
        marker.className = "conditional-required-marker";
        marker.setAttribute("aria-hidden", "true");
        marker.textContent = "*";
        container.querySelector("label")?.insertAdjacentElement("afterend", marker);
      }
      if (!required && marker) marker.remove();
    };

    civilStatus.addEventListener("change", syncSpouseRequirement);
    syncSpouseRequirement();
  });

  const cropSelector = 'select[name$="crop_type"]';
  const syncOtherCropField = (cropSelect) => {
    if (!cropSelect?.name || !cropSelect.form) return;
    const detailName = cropSelect.name.replace(/crop_type$/, "other_crop_name");
    const detail = cropSelect.form.elements.namedItem(detailName);
    if (!detail || detail instanceof RadioNodeList) return;
    const isOther = cropSelect.value === "Other Crop / Commodity";
    const container = detail.closest(".registration-field, .form-group");
    if (container) container.hidden = !isOther;
    detail.required = isOther;
    detail.toggleAttribute("aria-required", isOther);
    detail.disabled = !isOther;
    if (!isOther) {
      detail.setCustomValidity("");
      clear(detail);
    }
  };

  const initializeOtherCropFields = (root = document) => {
    if (root.matches?.(cropSelector)) syncOtherCropField(root);
    root.querySelectorAll?.(cropSelector).forEach(syncOtherCropField);
  };

  initializeOtherCropFields();
  document.addEventListener("change", (event) => {
    if (event.target.matches?.(cropSelector)) syncOtherCropField(event.target);
  });
  new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) initializeOtherCropFields(node);
      });
    });
  }).observe(document.body, {childList: true, subtree: true});

  document.querySelectorAll(".errorlist").forEach((errors) => {
    const container = errors.closest("label, .registration-field, .request-field, .account-field, .form-group, p") || errors.parentElement;
    container?.classList.add("has-error");
    container?.querySelectorAll(controls).forEach(mark);
  });
});

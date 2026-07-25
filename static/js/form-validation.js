document.addEventListener("DOMContentLoaded", () => {
  const controls = "input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea";
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
    form.addEventListener("submit", () => {
      form.classList.add("fmis-form-submitted");
      form.querySelectorAll(controls).forEach((field) => {
        if (field.validity && !field.validity.valid) mark(field);
      });
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
    if (!field.value) field.value = "09";
    field.addEventListener("input", enforcePrefix);
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

  document.querySelectorAll(".errorlist").forEach((errors) => {
    const container = errors.closest("label, .registration-field, .request-field, .account-field, .form-group, p") || errors.parentElement;
    container?.classList.add("has-error");
    container?.querySelectorAll(controls).forEach(mark);
  });
});

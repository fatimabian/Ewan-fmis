document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-single-submit]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }

      form.dataset.submitting = "true";
      const submitter = event.submitter;
      if (submitter) {
        // Wait until the browser has captured the clicked button's name and
        // value for the POST body before disabling it.
        window.setTimeout(() => {
          submitter.disabled = true;
          submitter.setAttribute("aria-disabled", "true");
        }, 0);
      }
    });
  });
});

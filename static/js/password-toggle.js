document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-password-toggle]").forEach(button => {
        const inputId = button.getAttribute("aria-controls");
        const input = inputId ? document.getElementById(inputId) : null;
        const icon = button.querySelector("i");

        if (!input || !icon) return;

        button.addEventListener("click", () => {
            const willShow = input.type === "password";
            input.type = willShow ? "text" : "password";
            icon.className = willShow ? "bi bi-eye-slash" : "bi bi-eye";
            button.setAttribute("aria-pressed", String(willShow));
            button.setAttribute("aria-label", willShow ? "Hide password" : "Show password");
            button.title = willShow ? "Hide password" : "Show password";
            input.focus({ preventScroll: true });
        });
    });
});

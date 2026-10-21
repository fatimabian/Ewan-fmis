(function () {
    "use strict";

    document.querySelectorAll("[data-compact-file-upload]").forEach(function (control) {
        var input = control.querySelector('input[type="file"]');
        var clear = control.querySelector('input[type="checkbox"]');
        var currentLink = control.querySelector('.compact-file-native a');
        var name = control.querySelector("[data-compact-file-name]");
        var download = control.querySelector("[data-compact-file-download]");
        var remove = control.querySelector("[data-compact-file-remove]");
        if (!input || !name || !download || !remove) return;

        var initial = currentLink ? {
            name: (currentLink.textContent || "Current picture").trim().split(/[\\/]/).pop(),
            url: currentLink.href
        } : null;

        function showEmpty() {
            name.textContent = "No file selected";
            name.classList.add("is-empty");
            download.hidden = true;
            download.removeAttribute("href");
            remove.hidden = true;
        }

        function showFile(fileName, url) {
            name.textContent = fileName;
            name.classList.remove("is-empty");
            download.hidden = !url;
            if (url) download.href = url;
            else download.removeAttribute("href");
            remove.hidden = false;
        }

        if (initial) showFile(initial.name, initial.url);
        else showEmpty();

        input.addEventListener("change", function () {
            var file = input.files && input.files[0];
            if (!file) {
                if (initial && !(clear && clear.checked)) showFile(initial.name, initial.url);
                else showEmpty();
                return;
            }
            if (clear) clear.checked = false;
            showFile(file.name, "");
        });

        remove.addEventListener("click", function () {
            var replacingExisting = Boolean(input.files && input.files.length && initial);
            input.value = "";
            input.dispatchEvent(new Event("fmis:draft-file-cleared", {bubbles: true}));
            if (replacingExisting) {
                if (clear) clear.checked = false;
                showFile(initial.name, initial.url);
                return;
            }
            if (clear && initial) clear.checked = true;
            showEmpty();
        });
    });
})();

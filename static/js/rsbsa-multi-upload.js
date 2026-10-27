(() => {
    const input = document.querySelector("[data-rsbsa-file-input]");
    const list = document.getElementById("rsbsaFileList");
    const listLabel = document.getElementById("rsbsaFileListLabel");
    const summary = document.getElementById("rsbsaFileSummary");
    if (!input || !list || !summary || typeof DataTransfer !== "function") return;

    let files = [];
    let syncing = false;
    const fileKey = (file) => [file.name, file.size, file.lastModified].join("::");
    const formatSize = (bytes) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024).toLocaleString()} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const syncInput = () => {
        const transfer = new DataTransfer();
        files.forEach((file) => transfer.items.add(file));
        syncing = true;
        input.files = transfer.files;
        syncing = false;
    };

    const render = () => {
        list.replaceChildren();
        files.forEach((file, index) => {
            const item = document.createElement("li");
            item.className = "rsbsa-file-item";
            const name = document.createElement("span");
            name.className = "rsbsa-file-item-name";
            name.textContent = file.name;
            name.title = file.name;
            const size = document.createElement("span");
            size.className = "rsbsa-file-item-size";
            size.textContent = `· ${formatSize(file.size)}`;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "rsbsa-file-remove";
            remove.setAttribute("aria-label", `Remove ${file.name}`);
            remove.textContent = "×";
            remove.addEventListener("click", () => {
                files.splice(index, 1);
                syncInput();
                render();
            });
            item.append(name, size, remove);
            list.append(item);
        });
        summary.textContent = files.length
            ? `${files.length} file${files.length === 1 ? "" : "s"} selected`
            : "No files selected";
        if (listLabel) listLabel.hidden = files.length === 0;
    };

    input.addEventListener("change", () => {
        if (syncing) return;
        const known = new Set(files.map(fileKey));
        [...input.files].forEach((file) => {
            if (!known.has(fileKey(file))) {
                files.push(file);
                known.add(fileKey(file));
            }
        });
        syncInput();
        render();
    });
})();

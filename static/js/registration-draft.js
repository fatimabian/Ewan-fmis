(function () {
    "use strict";

    var databaseName = "fmis-registration-drafts";
    var storeName = "uploads";
    var draftPrefix = "/farmers/new/:";
    var valuesKey = draftPrefix + "form-values";
    var saveTimer = null;

    function openDatabase() {
        return new Promise(function (resolve, reject) {
            if (!window.indexedDB) {
                reject(new Error("IndexedDB is unavailable"));
                return;
            }
            var request = indexedDB.open(databaseName, 1);
            request.onupgradeneeded = function () {
                if (!request.result.objectStoreNames.contains(storeName)) {
                    request.result.createObjectStore(storeName, {keyPath: "key"});
                }
            };
            request.onsuccess = function () { resolve(request.result); };
            request.onerror = function () { reject(request.error); };
        });
    }

    async function withStore(mode, callback) {
        var database = await openDatabase();
        return new Promise(function (resolve, reject) {
            var transaction = database.transaction(storeName, mode);
            var result;
            transaction.oncomplete = function () {
                database.close();
                resolve(result);
            };
            transaction.onerror = function () {
                database.close();
                reject(transaction.error);
            };
            result = callback(transaction.objectStore(storeName));
        });
    }

    function keyFor(input) {
        return draftPrefix + input.name;
    }

    async function saveInput(input) {
        if (!input.name) return;
        var files = Array.from(input.files || []);
        await withStore("readwrite", function (store) {
            if (!files.length) return store.delete(keyFor(input));
            return store.put({key: keyFor(input), files: files, savedAt: Date.now()});
        });
    }

    async function restoreInput(input) {
        if (!input.name || input.files.length || !window.DataTransfer) return;
        var record;
        await withStore("readonly", function (store) {
            var request = store.get(keyFor(input));
            request.onsuccess = function () { record = request.result; };
            return request;
        });
        if (!record) return;
        var transfer = new DataTransfer();
        record.files.forEach(function (file) { transfer.items.add(file); });
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", {bubbles: true}));
    }

    async function clearDrafts() {
        window.localStorage.removeItem(valuesKey);
        await withStore("readwrite", function (store) {
            var request = store.openCursor();
            request.onsuccess = function () {
                var cursor = request.result;
                if (!cursor) return;
                if (String(cursor.key).indexOf(draftPrefix) === 0) cursor.delete();
                cursor.continue();
            };
            return request;
        });
    }

    function serialiseForm(form) {
        var values = {};
        Array.from(form.elements).forEach(function (field) {
            if (!field.name || field.type === "file" || field.type === "submit" || field.type === "button" || field.name === "csrfmiddlewaretoken") return;
            if (!values[field.name]) values[field.name] = [];
            values[field.name].push(
                field.type === "checkbox" || field.type === "radio"
                    ? {type: field.type, checked: field.checked, value: field.value}
                    : {type: field.type, value: field.value}
            );
        });
        return values;
    }

    function saveValues(form) {
        try {
            window.localStorage.setItem(valuesKey, JSON.stringify(serialiseForm(form)));
        } catch (error) {
            // A full or unavailable localStorage must never block registration.
        }
    }

    function queueSave(form) {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(function () { saveValues(form); }, 120);
    }

    function setField(field, record) {
        if (!field || !record) return;
        if (field.type === "checkbox" || field.type === "radio") field.checked = Boolean(record.checked);
        else field.value = record.value == null ? "" : record.value;
        field.dispatchEvent(new Event("input", {bubbles: true}));
        field.dispatchEvent(new Event("change", {bubbles: true}));
    }

    function restoreValues(form) {
        var values;
        try { values = JSON.parse(window.localStorage.getItem(valuesKey) || "null"); }
        catch (error) { return; }
        if (!values) return;

        // Recreate saved inline formset rows before restoring their controls.
        ["parcels", "crops", "documents"].forEach(function (prefix) {
            var wanted = Number((values[prefix + "-TOTAL_FORMS"] || [])[0]?.value || 0);
            var button = form.querySelector('.add-form-row[data-prefix="' + prefix + '"]');
            var total = form.querySelector('[name="' + prefix + '-TOTAL_FORMS"]');
            while (button && total && Number(total.value) < wanted) button.click();
        });

        Object.keys(values).forEach(function (name) {
            var fields = Array.from(form.elements).filter(function (field) { return field.name === name; });
            var records = Array.isArray(values[name]) ? values[name] : [values[name]];
            fields.forEach(function (field, index) {
                var record = records[index] || records.find(function (item) { return item.value === field.value; });
                setField(field, record);
            });
        });
        form.dispatchEvent(new CustomEvent("fmis:registration-draft-restored", {bubbles: true}));
    }

    var clearMarker = document.querySelector("[data-clear-registration-draft]");
    if (clearMarker) {
        clearDrafts().catch(function () {});
        return;
    }

    var form = document.getElementById("rsbsaRegistration");
    if (!form) return;
    window.setTimeout(function () { restoreValues(form); }, 0);
    form.addEventListener("input", function () { queueSave(form); });
    form.addEventListener("change", function (event) {
        queueSave(form);
        if (event.target.matches('input[type="file"]')) {
            saveInput(event.target).catch(function () {});
        }
    });
    form.addEventListener("fmis:draft-file-cleared", function (event) {
        if (event.target.matches('input[type="file"]')) {
            saveInput(event.target).catch(function () {});
        }
    });
    form.querySelectorAll('input[type="file"]').forEach(function (input) {
        restoreInput(input).catch(function () {});
    });
    form.querySelectorAll("[data-cancel-registration]").forEach(function (link) {
        link.addEventListener("click", function (event) {
            event.preventDefault();
            if (!window.confirm("Cancel this registration? All drafted information and selected files will be removed.")) return;
            clearDrafts().finally(function () { window.location.assign(link.href); });
        });
    });
    window.FMISRegistrationDraft = {save: function () { saveValues(form); }, clear: clearDrafts};
})();

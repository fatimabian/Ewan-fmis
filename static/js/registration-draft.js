(function () {
    "use strict";

    var databaseName = "fmis-registration-drafts";
    var storeName = "uploads";
    var draftPrefix = "/farmers/new/:";
    var maximumAge = 2 * 60 * 60 * 1000;

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
        if (!record || Date.now() - record.savedAt > maximumAge) return;
        var transfer = new DataTransfer();
        record.files.forEach(function (file) { transfer.items.add(file); });
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", {bubbles: true}));
    }

    async function clearDrafts() {
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

    async function removeExpired() {
        await withStore("readwrite", function (store) {
            var request = store.openCursor();
            request.onsuccess = function () {
                var cursor = request.result;
                if (!cursor) return;
                if (Date.now() - cursor.value.savedAt > maximumAge) cursor.delete();
                cursor.continue();
            };
            return request;
        });
    }

    var clearMarker = document.querySelector("[data-clear-registration-draft]");
    if (clearMarker) {
        clearDrafts().catch(function () {});
        return;
    }

    var form = document.getElementById("rsbsaRegistration");
    if (!form) return;
    removeExpired().catch(function () {});
    form.addEventListener("change", function (event) {
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
})();

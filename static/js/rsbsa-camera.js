(() => {
    const openButton = document.getElementById("rsbsaCameraOpen");
    const modal = document.getElementById("rsbsaCameraModal");
    const video = document.getElementById("rsbsaCameraVideo");
    const canvas = document.getElementById("rsbsaCameraCanvas");
    const captureButton = document.getElementById("rsbsaCameraCapture");
    const cancelButton = document.getElementById("rsbsaCameraCancel");
    const backdrop = document.getElementById("rsbsaCameraBackdrop");
    const status = document.getElementById("rsbsaCameraStatus");
    const input = document.querySelector("[data-rsbsa-camera-source]");
    if (!openButton || !modal || !video || !canvas || !captureButton || !input) return;

    const consentKey = "fmis-rsbsa-camera-confirmed-v1";
    let stream = null;

    const rememberConsent = () => {
        try {
            window.localStorage.setItem(consentKey, "true");
        } catch (_error) {
            // Private browsing can block storage. Camera use still remains available.
        }
    };

    const hasRememberedConsent = () => {
        try {
            return window.localStorage.getItem(consentKey) === "true";
        } catch (_error) {
            return false;
        }
    };

    const setStatus = (message) => {
        if (status) status.textContent = message;
    };

    const stopCamera = () => {
        stream?.getTracks().forEach((track) => track.stop());
        stream = null;
        video.srcObject = null;
        captureButton.disabled = true;
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
        openButton.focus({preventScroll: true});
    };

    const cameraErrorMessage = (error) => {
        if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
            return "Camera access was not allowed. Enable camera permission in this browser, or choose a file instead.";
        }
        if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") {
            return "No camera was found on this device. Choose a file instead.";
        }
        if (error?.name === "NotReadableError" || error?.name === "TrackStartError") {
            return "The camera is busy or unavailable. Close other camera apps and try again, or upload the file.";
        }
        return "The camera could not be started. Check the device camera and browser permission, or upload the file.";
    };

    const startCamera = async (rememberAfterStart = false) => {
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        setStatus("Starting the camera…");
        captureButton.disabled = true;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: {ideal: "environment"},
                    width: {ideal: 1920},
                    height: {ideal: 2560},
                },
                audio: false,
            });
            if (rememberAfterStart) rememberConsent();
            video.srcObject = stream;
            await video.play();
            captureButton.disabled = false;
            setStatus("Position the whole form inside the frame and keep the handwriting clear.");
            captureButton.focus({preventScroll: true});
        } catch (error) {
            stopCamera();
            window.fmisFeedback?.(cameraErrorMessage(error), "error");
        }
    };

    const verifyAndStart = async () => {
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
            window.fmisFeedback?.(
                "Camera capture is unavailable in this browser. Open the secure FMIS website in a current browser, or choose a file instead.",
                "warning"
            );
            return;
        }
        openButton.disabled = true;
        openButton.setAttribute("aria-busy", "true");
        const originalButtonContent = openButton.innerHTML;
        openButton.innerHTML = '<span class="fmis-submit-spinner" aria-hidden="true"></span> Checking camera…';
        try {
            const devices = await navigator.mediaDevices.enumerateDevices?.();
            if (devices?.length && !devices.some((device) => device.kind === "videoinput")) {
                window.fmisFeedback?.("No camera was found on this device. Choose a file instead.", "warning");
                return;
            }
            if (hasRememberedConsent()) {
                await startCamera();
                return;
            }
            const message = "FMIS will use this device camera only to capture an RSBSA copy for this farmer record. The photo will not fill the registration fields. Continue?";
            if (window.fmisFeedback) {
                window.fmisFeedback(message, "confirm", () => {
                    startCamera(true);
                });
            } else if (window.confirm(message)) {
                await startCamera(true);
            }
        } catch (error) {
            window.fmisFeedback?.(cameraErrorMessage(error), "error");
        } finally {
            openButton.disabled = false;
            openButton.removeAttribute("aria-busy");
            openButton.innerHTML = originalButtonContent;
        }
    };

    const capturePhoto = async () => {
        if (!stream || !video.videoWidth || !video.videoHeight) return;
        captureButton.disabled = true;
        captureButton.setAttribute("aria-busy", "true");
        setStatus("Preparing the captured form…");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
        if (!blob) {
            captureButton.disabled = false;
            captureButton.removeAttribute("aria-busy");
            setStatus("The photo could not be captured. Please try again.");
            return;
        }
        const file = new File([blob], `rsbsa-page-1-${Date.now()}.jpg`, {type: "image/jpeg"});
        if (typeof DataTransfer !== "function") {
            captureButton.disabled = false;
            captureButton.removeAttribute("aria-busy");
            setStatus("This browser cannot attach the captured photo. Update the browser or choose a file.");
            return;
        }
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        stopCamera();
        input.dispatchEvent(new Event("change", {bubbles: true}));
        captureButton.removeAttribute("aria-busy");
    };

    openButton.addEventListener("click", verifyAndStart);
    captureButton.addEventListener("click", capturePhoto);
    cancelButton?.addEventListener("click", stopCamera);
    backdrop?.addEventListener("click", stopCamera);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !modal.hidden) stopCamera();
    });
    window.addEventListener("pagehide", stopCamera);
})();

const form = document.getElementById("generateForm");
const loadButton = document.getElementById("loadButton");
const generateButton = document.getElementById("generateButton");
const statusLine = document.getElementById("status");
const result = document.getElementById("result");
const metadata = document.getElementById("metadata");
const progress = document.getElementById("progress");
const progressBar = document.getElementById("progressBar");
const modeInput = document.getElementById("mode");
const imageInput = document.getElementById("image");
const imageInputGroup = document.getElementById("imageInputGroup");
const appBaseUrl = new URL("./", window.location.href);

function appUrl(path) {
    return new URL(String(path).replace(/^\/+/, ""), appBaseUrl).toString();
}

function setBusy(isBusy, message) {
    loadButton.disabled = isBusy;
    generateButton.disabled = isBusy;
    statusLine.textContent = message;
    statusLine.className = `status ${isBusy ? "busy" : ""}`;
}

function setProgress(percentage) {
    const bounded = Math.max(0, Math.min(100, Number(percentage) || 0));
    progress.hidden = false;
    progressBar.style.width = `${bounded}%`;
}

function hideProgress() {
    progress.hidden = true;
    progressBar.style.width = "0%";
}

function readPayload() {
    const formData = new FormData(form);
    return {
        mode: String(formData.get("mode") || "text"),
        prompt: String(formData.get("prompt") || ""),
        width: Number(formData.get("width")),
        height: Number(formData.get("height")),
        num_inference_steps: Number(formData.get("num_inference_steps")),
        guidance_scale: Number(formData.get("guidance_scale")),
        max_sequence_length: Number(formData.get("max_sequence_length")),
        seed: formData.get("seed") ? Number(formData.get("seed")) : null,
    };
}

function readRequestBody() {
    const payload = readPayload();
    if (payload.mode !== "image") {
        return payload;
    }

    const body = new FormData();
    for (const [key, value] of Object.entries(payload)) {
        if (value !== null && value !== undefined) {
            body.append(key, String(value));
        }
    }
    if (imageInput.files[0]) {
        body.append("image", imageInput.files[0]);
    }
    return body;
}

async function postJson(url, payload = {}) {
    const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
        throw new Error(data.error || `Request failed with ${response.status}`);
    }
    return data;
}

async function postStream(url, payload, onMessage) {
    const isFormData = payload instanceof FormData;
    const response = await fetch(url, {
        method: "POST",
        headers: isFormData ? undefined : {"Content-Type": "application/json"},
        body: isFormData ? payload : JSON.stringify(payload),
    });

    if (!response.ok) {
        let message = `Request failed with ${response.status}`;
        try {
            const data = await response.json();
            message = data.error || message;
        } catch (_error) {
            message = await response.text() || message;
        }
        throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const {value, done} = await reader.read();
        if (done) {
            break;
        }

        buffer += decoder.decode(value, {stream: true});
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const event of events) {
            const dataLines = event
                .split("\n")
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).trim());
            if (dataLines.length === 0) {
                continue;
            }
            onMessage(JSON.parse(dataLines.join("\n")));
        }
    }
}

loadButton.addEventListener("click", async () => {
    try {
        setBusy(true, "Loading model. This can take a while the first time.");
        await postJson(appUrl("api/load"));
        setBusy(false, "Model loaded.");
    } catch (error) {
        setBusy(false, `Load failed: ${error.message}`);
    }
});

modeInput.addEventListener("change", () => {
    const imageMode = modeInput.value === "image";
    imageInputGroup.hidden = !imageMode;
    imageInput.required = imageMode;
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const payload = readPayload();
    if (!payload.prompt.trim()) {
        statusLine.textContent = "Prompt is required.";
        return;
    }
    if (payload.mode === "image" && !imageInput.files[0]) {
        statusLine.textContent = "Image reference mode requires an input image.";
        return;
    }

    try {
        setBusy(true, "Generating image.");
        setProgress(0);
        result.className = "result empty";
        result.textContent = "Generation running...";
        metadata.textContent = "";

        let completed = false;
        await postStream(appUrl("api/generate-stream"), readRequestBody(), (data) => {
            if (data.type === "status") {
                statusLine.textContent = data.message;
                return;
            }

            if (data.type === "progress") {
                setProgress(data.percentage);
                result.textContent = `Step ${data.step} of ${data.total_steps}`;
                statusLine.textContent = `Generating image: ${data.percentage}%`;
                return;
            }

            if (data.type === "error") {
                throw new Error(data.message || "Generation failed");
            }

            if (data.type === "complete") {
                completed = true;
                setProgress(100);

                const image = document.createElement("img");
                image.src = `data:image/png;base64,${data.image}`;
                image.alt = "Generated image";

                result.replaceChildren(image);
                result.className = "result";
                metadata.innerHTML = `
                    <a href="${appUrl(data.image_url)}" target="_blank" rel="noopener">Open saved PNG</a>
                    <span>${data.parameters.mode}</span>
                    <span>Seed: ${data.seed}</span>
                    <span>${data.parameters.width}x${data.parameters.height}</span>
                    <span>${data.parameters.num_inference_steps} steps</span>
                    <span>Guidance ${data.parameters.guidance_scale}</span>
                    <span>Seq ${data.parameters.max_sequence_length}</span>
                    <span>${data.elapsed_seconds}s</span>
                `;
            }
        });

        if (!completed) {
            throw new Error("Generation stream ended without a final image");
        }
        setBusy(false, "Generation complete.");
    } catch (error) {
        result.className = "result empty error";
        result.textContent = error.message;
        hideProgress();
        setBusy(false, `Generation failed: ${error.message}`);
    }
});

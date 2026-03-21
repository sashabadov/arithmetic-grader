// Fill in after deploying backend to Render:
const BACKEND_URL = "https://<your-render-app>.onrender.com/grade";

const COLD_START_MS = 5000;
const COLD_START_MSG = "First request may take ~30 seconds while the server wakes up\u2026";

let worksheetFile = null;
let answerKeyFile = null;

const btnGrade = document.getElementById("btn-grade");
const statusEl = document.getElementById("status");
const statusMsg = document.getElementById("status-msg");
const errorBox = document.getElementById("error-box");

// Wire up a drop zone
function wireDropZone(zoneId, inputId, filenameId, onFile) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const filenameEl = document.getElementById(filenameId);

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") input.click();
  });

  input.addEventListener("change", () => {
    if (input.files[0]) setFile(input.files[0]);
  });

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("drag-over");
  });

  zone.addEventListener("dragleave", () => {
    zone.classList.remove("drag-over");
  });

  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
  });

  function setFile(file) {
    onFile(file);
    filenameEl.textContent = file.name;
    zone.classList.add("has-file");
  }
}

wireDropZone("drop-worksheet", "input-worksheet", "ws-filename", (file) => {
  worksheetFile = file;
  btnGrade.disabled = false;
});

wireDropZone("drop-answerkey", "input-answerkey", "ak-filename", (file) => {
  answerKeyFile = file;
});

// Grade button
btnGrade.addEventListener("click", async () => {
  if (!worksheetFile) return;

  const formData = new FormData();
  formData.append("worksheet", worksheetFile);
  if (answerKeyFile) {
    formData.append("answer_key", answerKeyFile);
  }
  const colsVal = document.getElementById("input-cols").value.trim();
  if (colsVal) {
    formData.append("cols", colsVal);
  }

  showStatus("Grading\u2026");
  hideError();
  btnGrade.disabled = true;

  const coldStartTimer = setTimeout(() => {
    statusMsg.textContent = COLD_START_MSG;
  }, COLD_START_MS);

  try {
    const response = await fetch(BACKEND_URL, {
      method: "POST",
      body: formData,
      // Do NOT set Content-Type — browser must set multipart boundary automatically
    });

    clearTimeout(coldStartTimer);

    if (response.ok) {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "graded.pdf";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      hideStatus();
    } else {
      let detail = "An unknown error occurred.";
      try {
        const err = await response.json();
        detail = err.detail ?? detail;
      } catch (_) {}
      showError(detail);
      hideStatus();
    }
  } catch (_networkErr) {
    clearTimeout(coldStartTimer);
    showError("Could not reach the server. Check your connection and try again.");
    hideStatus();
  } finally {
    btnGrade.disabled = false;
  }
});

function showStatus(msg) {
  statusMsg.textContent = msg;
  statusEl.hidden = false;
}

function hideStatus() {
  statusEl.hidden = true;
}

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.hidden = false;
}

function hideError() {
  errorBox.hidden = true;
}

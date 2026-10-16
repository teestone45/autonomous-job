"use strict";

const byId = (id) => document.getElementById(id);
const value = (id) => byId(id).value.trim();
let busy = false;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(path, data) {
  const response = await fetch(`/api/${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
    },
    body: JSON.stringify(data),
  });
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) {
    throw new Error(`Server returned HTTP ${response.status}. Check the deployment logs or sign in again.`);
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}

async function task(button, message, action) {
  if (busy) return;
  busy = true;
  button.disabled = true;
  byId("status").textContent = message;
  byId("status").classList.remove("error");
  try {
    await action();
    byId("status").textContent = "Done. Review your results before using them.";
  } catch (error) {
    byId("status").textContent = error.message;
    byId("status").classList.add("error");
  } finally {
    busy = false;
    button.disabled = false;
  }
}

function requireValue(id, label) {
  const text = value(id);
  if (!text) throw new Error(`Enter ${label}.`);
  return text;
}

function download(text, filename) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = element("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function editable(labelText, initial, multiline = false) {
  const label = element("label", labelText);
  const input = element(multiline ? "textarea" : "input");
  input.value = initial;
  if (multiline) input.rows = 10;
  label.append(input);
  return { label, input };
}

function checkbox(text) {
  const label = element("label", "", "check");
  const input = element("input");
  input.type = "checkbox";
  label.append(input, document.createTextNode(text));
  return { label, input };
}

function editor(parent, email, kind, recipient = "", resumeInput = null) {
  const container = element("section");
  const subject = editable("Email subject", email.subject);
  const body = editable("Exact email body (review and edit)", email.body, true);
  const to = editable("Recipient email", recipient);
  to.input.type = "email";
  const consent = checkbox(kind === "application"
    ? "The candidate authorized this application to this employer contact."
    : "This person explicitly opted in to this service follow-up.");
  const accepts = checkbox("I verified the job listing accepts applications by email.");
  const approved = checkbox("I reviewed this exact recipient, subject, message, and attachment and approve sending.");
  const send = element("button", "Send approved email");
  send.disabled = true;
  const result = element("p", "", "note");
  let sent = false;
  container.append(to.label, subject.label, body.label, consent.label);
  if (kind === "application") container.append(accepts.label);
  if (resumeInput) container.append(element("p", "The reviewed resume above will be attached as resume.txt.", "note"));
  container.append(approved.label, send, result);
  parent.replaceChildren(container);
  const update = () => {
    send.disabled = sent || !approved.input.checked || !consent.input.checked
      || (kind === "application" && !accepts.input.checked);
  };
  for (const input of [subject.input, body.input, to.input, ...(resumeInput ? [resumeInput] : [])]) {
    input.addEventListener("input", () => {
      approved.input.checked = false;
      update();
    });
  }
  for (const check of [approved.input, consent.input, accepts.input]) {
    check.addEventListener("change", update);
  }
  send.addEventListener("click", async () => {
    await task(send, "Sending the reviewed email through Resend...", async () => {
      const response = await api("send", {
        resend_key: requireValue("resend-key", "your Resend API key"),
        sender: requireValue("sender", "your verified sender email"),
        recipient: to.input.value,
        subject: subject.input.value,
        body: body.input.value,
        attachment: resumeInput ? resumeInput.value : "",
        kind,
        recipient_consented: consent.input.checked,
        client_consented: kind === "service" && consent.input.checked,
        accepts_email: accepts.input.checked,
        approved: approved.input.checked,
      });
      sent = true;
      result.textContent = `Accepted by Resend. Message ID: ${response.id}. Check Resend for delivery status.`;
    });
    update();
  });
}

byId("show-jobs").addEventListener("click", () => {
  byId("jobs-panel").hidden = false;
  byId("service-panel").hidden = true;
});
byId("show-service").addEventListener("click", () => {
  byId("jobs-panel").hidden = true;
  byId("service-panel").hidden = false;
});

byId("find-jobs").addEventListener("click", () => {
  task(byId("find-jobs"), "Fetching the latest Remote OK listings...", async () => {
    const result = await api("jobs", { roles: requireValue("roles", "at least one target role") });
    byId("job-results").replaceChildren();
    byId("job-results").append(element("p", `${result.jobs.length} matching listings. Job eligibility must be checked individually.`));
    result.jobs.forEach(jobCard);
  });
});

function jobCard(job) {
  const card = element("article", "", "panel");
  card.append(element("h3", job.title), element("p", `${job.company} | ${job.location}`));
  const link = element("a", "View listing on Remote OK");
  link.href = job.url;
  link.target = "_blank";
  link.rel = "noopener";
  const scoreButton = element("button", "Score resume match");
  const prepareButton = element("button", "Generate application materials");
  const scoreResult = element("p");
  const materials = element("div");
  const jobData = () => ({
    api_key: requireValue("api-key", "your OpenAI API key"),
    name: requireValue("name", "your name"),
    resume: requireValue("resume", "your resume"),
    title: job.title,
    company: job.company,
    description: job.description,
  });
  scoreButton.addEventListener("click", () => {
    task(scoreButton, "Scoring this role against your resume...", async () => {
      const result = await api("score", jobData());
      scoreResult.textContent = `${result.score}/100 - ${result.reasoning}`;
    });
  });
  prepareButton.addEventListener("click", () => {
    task(prepareButton, "Preparing a resume, then a cover letter (two AI requests)...", async () => {
      const data = jobData();
      const resumeResult = await api("tailored-resume", data);
      // Retain a successful resume even if the subsequent cover-letter call fails.
      materials.replaceChildren();
      const resume = editable("Tailored resume - verify every fact before use", resumeResult.resume, true);
      const downloadButton = element("button", "Download reviewed resume");
      downloadButton.addEventListener("click", () => download(resume.input.value, "resume.txt"));
      materials.append(resume.label, downloadButton);
      const cover = await api("cover-letter", data);
      const emailPanel = element("div");
      materials.append(emailPanel);
      editor(emailPanel, cover.email, "application", "", resume.input);
    });
  });
  card.append(link, element("p", "Source: Remote OK", "note"), scoreButton, prepareButton, scoreResult, materials);
  byId("job-results").append(card);
}

let review = null;
let reviewedInput = null;

function resetReview() {
  review = null;
  reviewedInput = null;
  byId("review-result").replaceChildren();
  byId("service-email").replaceChildren();
  byId("improved-result").replaceChildren();
  byId("payment-verified").checked = false;
  byId("offer").disabled = true;
  byId("improve").disabled = true;
}

for (const id of ["client-name", "client-email", "client-resume", "client-consent", "service-description", "price", "payment"]) {
  byId(id).addEventListener("input", resetReview);
}

byId("review-resume").addEventListener("click", () => {
  task(byId("review-resume"), "Reviewing the opted-in client's resume...", async () => {
    resetReview();
    if (!byId("client-consent").checked) throw new Error("Confirm the client's review and email consent.");
    const snapshot = {
      name: requireValue("client-name", "the client's name"),
      recipient: requireValue("client-email", "the client's email"),
      resume: requireValue("client-resume", "the client's resume"),
      client_consented: true,
    };
    reviewedInput = snapshot;
    const result = await api("review", {
      ...snapshot, api_key: requireValue("api-key", "your OpenAI API key"),
    });
    if (reviewedInput !== snapshot) {
      throw new Error("Client details changed during the review. Review the updated input again.");
    }
    review = result.review;
    const nodes = [element("p", review.summary)];
    for (const issue of review.issues) {
      nodes.push(element("h3", issue.issue), element("p", issue.recommendation));
    }
    byId("review-result").replaceChildren(...nodes);
    byId("offer").disabled = false;
    byId("improve").disabled = !byId("payment-verified").checked;
  });
});

byId("offer").addEventListener("click", () => {
  task(byId("offer"), "Drafting the optional service offer...", async () => {
    if (!review || !reviewedInput) throw new Error("Review this client's resume first.");
    const snapshot = reviewedInput;
    const result = await api("offer", {
      ...snapshot, review,
      api_key: requireValue("api-key", "your OpenAI API key"),
      service_description: requireValue("service-description", "your service description"),
      price: value("price"), payment_instructions: value("payment"),
    });
    if (reviewedInput !== snapshot) {
      throw new Error("Client details changed. Review the updated input again.");
    }
    editor(byId("service-email"), result.email, "service", snapshot.recipient);
  });
});

byId("payment-verified").addEventListener("change", () => {
  byId("improve").disabled = !review || !byId("payment-verified").checked;
  if (!byId("payment-verified").checked) byId("improved-result").replaceChildren();
});

byId("improve").addEventListener("click", () => {
  task(byId("improve"), "Preparing the paid resume improvement...", async () => {
    if (!review || !reviewedInput) throw new Error("Review this client's resume first.");
    const snapshot = reviewedInput;
    const result = await api("improve", {
      ...snapshot, review,
      api_key: requireValue("api-key", "your OpenAI API key"),
      service_description: requireValue("service-description", "your service description"),
      payment_verified: byId("payment-verified").checked,
    });
    if (reviewedInput !== snapshot || !byId("payment-verified").checked) {
      throw new Error("Client details or payment confirmation changed. Review before continuing.");
    }
    const resume = editable("Improved resume - review with your client", result.resume, true);
    const downloadButton = element("button", "Download reviewed resume");
    downloadButton.addEventListener("click", () => download(resume.input.value, "improved-resume.txt"));
    byId("improved-result").replaceChildren(resume.label, downloadButton);
  });
});

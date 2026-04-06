const DEFAULT_BASE_URL = 'http://localhost:8000';
const API_BASE_URL = (import.meta.env?.VITE_BACKEND_URL || DEFAULT_BASE_URL).replace(/\/$/, '');

const DEFAULT_HEADERS = {
    'Content-Type': 'application/json'
};

async function request(path, options = {}) {
    const hasFormDataBody =
        typeof FormData !== 'undefined' &&
        options?.body instanceof FormData;

    const response = await fetch(`${API_BASE_URL}${path}`, {
        ...options,
        headers: {
            ...(hasFormDataBody ? {} : DEFAULT_HEADERS),
            ...(options.headers || {})
        }
    });

    if (!response.ok) {
        const payload = await safeJson(response);
        const detail = payload?.detail || response.statusText;
        throw new Error(`API request failed (${response.status}): ${detail}`);
    }

    if (response.status === 204) {
        return null;
    }

    return response.json();
}

async function safeJson(response) {
    try {
        return await response.json();
    } catch {
        return null;
    }
}

function appendUploadFormData(formData, uploadPayload) {
    const title = String(uploadPayload?.title ?? '').trim();
    const documents = Array.isArray(uploadPayload?.documents) ? uploadPayload.documents : [];
    if (!title) {
        throw new Error('A title is required for upload.');
    }
    if (!documents.length) {
        throw new Error('At least one document is required for upload.');
    }

    const manifestDocuments = documents.map((entry, index) => {
        const file = entry?.file;
        if (!file) {
            throw new Error(`Document #${index + 1} is missing an uploaded file.`);
        }
        const name = String(entry?.name || '').trim();
        const date = String(entry?.date || '').trim();
        const type = String(entry?.type || '').trim();
        const typeOther = String(entry?.typeOther || '').trim();
        if (!name || !date || !type) {
            throw new Error(`Document #${index + 1} must include name, date, and type.`);
        }
        return {
            name,
            date,
            type,
            typeOther: type === 'Other' ? typeOther : undefined,
            fileName: file.name
        };
    });

    formData.append(
        'manifest',
        JSON.stringify({
            title,
            documents: manifestDocuments
        })
    );
    documents.forEach((entry) => {
        formData.append('files', entry.file, entry.file.name);
    });
}

export async function createRun() {
    return request('/runs', {
        method: 'POST',
        body: JSON.stringify({})
    });
}

export async function updateRunFromUpload(runId, uploadPayload) {
    const formData = new FormData();
    appendUploadFormData(formData, uploadPayload);
    return request(`/runs/${runId}/upload-documents`, {
        method: 'POST',
        body: formData
    });
}

export async function fetchRun(runId) {
    return request(`/runs/${runId}`);
}

export async function updateRunWorkflowStage(runId, workflowStage) {
    const normalized = String(workflowStage || '').trim();
    if (!normalized) {
        throw new Error('workflowStage is required.');
    }
    return request(`/runs/${runId}/workflow-stage`, {
        method: 'PUT',
        body: JSON.stringify({ workflowStage: normalized })
    });
}

export async function startRunExtraction(runId, extractionConfig = null) {
    const payload = extractionConfig ? { extractionConfig } : {};
    return request(`/runs/${runId}/extraction/start`, {
        method: 'POST',
        body: JSON.stringify(payload)
    });
}

export async function fetchRunExtractionStatus(runId) {
    return request(`/runs/${runId}/extraction/status`);
}

export async function fetchRunChecklist(runId) {
    return request(`/runs/${runId}/checklist`);
}

export async function updateRunChecklist(runId, checklistPayload) {
    return request(`/runs/${runId}/checklist`, {
        method: 'PUT',
        body: JSON.stringify(checklistPayload)
    });
}

export async function fetchRunDocuments(runId) {
    return request(`/runs/${runId}/documents`);
}

export async function startRunSummary(runId, summaryConfig = null) {
    const payload = summaryConfig ? { summaryConfig } : {};
    return request(`/runs/${runId}/summary/start`, {
        method: 'POST',
        body: JSON.stringify(payload)
    });
}

export async function fetchRunSummaryStatus(runId) {
    return request(`/runs/${runId}/summary/status`);
}

export function getApiBaseUrl() {
    return API_BASE_URL;
}

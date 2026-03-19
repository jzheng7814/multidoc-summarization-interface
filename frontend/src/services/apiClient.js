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

export async function fetchDocuments(caseId) {
    return request(`/cases/${caseId}/documents`);
}

export async function uploadDocuments(uploadPayload) {
    const caseName = String(uploadPayload?.caseName || '').trim();
    const documents = Array.isArray(uploadPayload?.documents) ? uploadPayload.documents : [];
    if (!caseName) {
        throw new Error('Case name is required for upload.');
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

    const formData = new FormData();
    formData.append(
        'manifest',
        JSON.stringify({
            caseName,
            documents: manifestDocuments
        })
    );
    documents.forEach((entry) => {
        formData.append('files', entry.file, entry.file.name);
    });
    return request('/cases/upload-documents', {
        method: 'POST',
        body: formData
    });
}

export async function createRunFromCaseId(caseId) {
    const normalized = String(caseId || '').trim();
    if (!normalized) {
        throw new Error('Case ID is required.');
    }
    return request('/runs/from-case-id', {
        method: 'POST',
        body: JSON.stringify({ caseId: normalized })
    });
}

export async function createRunFromUpload(uploadPayload) {
    const caseName = String(uploadPayload?.caseName || '').trim();
    const documents = Array.isArray(uploadPayload?.documents) ? uploadPayload.documents : [];
    if (!caseName) {
        throw new Error('Case name is required for upload.');
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

    const formData = new FormData();
    formData.append(
        'manifest',
        JSON.stringify({
            caseName,
            documents: manifestDocuments
        })
    );
    documents.forEach((entry) => {
        formData.append('files', entry.file, entry.file.name);
    });

    return request('/runs/upload-documents', {
        method: 'POST',
        body: formData
    });
}

export async function fetchRunDefaults() {
    return request('/runs/defaults');
}

export async function fetchRun(runId) {
    return request(`/runs/${runId}`);
}

export async function updateRunExtractionConfig(runId, extractionConfig) {
    return request(`/runs/${runId}/extraction-config`, {
        method: 'PUT',
        body: JSON.stringify(extractionConfig)
    });
}

export async function updateRunSummaryConfig(runId, summaryConfig) {
    return request(`/runs/${runId}/summary-config`, {
        method: 'PUT',
        body: JSON.stringify(summaryConfig)
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

export async function startSummaryJob(caseId, body) {
    return request(`/cases/${caseId}/summary`, {
        method: 'POST',
        body: JSON.stringify(body)
    });
}

export async function getSummaryJob(caseId, jobId) {
    return request(`/cases/${caseId}/summary/${jobId}`);
}

export async function fetchChecklist(caseId) {
    return request(`/cases/${caseId}/checklist`);
}

export async function startChecklistExtraction(caseId) {
    return request(`/cases/${caseId}/checklist/start`, {
        method: 'POST'
    });
}

export async function fetchChecklistStatus(caseId) {
    return request(`/cases/${caseId}/checklist/status`);
}

export async function fetchSummaryPrompt() {
    return request('/cases/summary/prompt');
}

export function getApiBaseUrl() {
    return API_BASE_URL;
}

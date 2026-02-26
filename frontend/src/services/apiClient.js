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

export async function createChatSession() {
    return request('/chat/session', { method: 'POST' });
}

export async function getChatSession(sessionId) {
    return request(`/chat/session/${sessionId}`);
}

export async function sendChatMessage(sessionId, body) {
    return request(`/chat/session/${sessionId}/message`, {
        method: 'POST',
        body: JSON.stringify(body)
    });
}

export function getApiBaseUrl() {
    return API_BASE_URL;
}

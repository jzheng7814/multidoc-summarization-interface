export const CASE_STATE_KIND = 'legal-case-workspace-state';
export const CASE_STATE_SCHEMA_VERSION = 1;

const parseDocumentId = (value) => {
    if (value == null) {
        return null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
};

const parseOffset = (value) => {
    if (value == null) {
        return null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
};

export const buildDocumentLookup = (documents = []) => {
    const lookup = {};
    documents.forEach((document) => {
        if (document?.id != null) {
            lookup[document.id] = document;
        }
    });
    return lookup;
};

export const normaliseImportedCaseState = (payload) => {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        throw new Error('Case state import must be a JSON object.');
    }

    const kind = payload.kind ?? payload.type;
    if (typeof kind === 'string' && kind.trim().length && kind !== CASE_STATE_KIND) {
        throw new Error(`Unsupported case state kind "${kind}".`);
    }

    const schemaVersion = payload.schemaVersion ?? payload.schema_version ?? null;
    if (schemaVersion != null && Number(schemaVersion) !== CASE_STATE_SCHEMA_VERSION) {
        throw new Error(`Unsupported case state schema version "${schemaVersion}".`);
    }

    const caseId = String(payload.caseId ?? payload.case_id ?? '').trim();
    if (!caseId) {
        throw new Error('Case state import is missing caseId.');
    }

    const summaryText = payload.summaryText ?? payload.summary_text ?? '';
    if (typeof summaryText !== 'string') {
        throw new Error('Case state import must include summaryText as a string.');
    }

    const prompt = payload.prompt ?? '';
    if (typeof prompt !== 'string') {
        throw new Error('Case state import must include prompt as a string.');
    }

    return {
        caseId,
        summaryText,
        prompt,
        items: payload.checklist?.items ?? payload.items
    };
};

export const normaliseImportedItems = (rawItems, allowedCategoryIds, documentLookup) => {
    if (!Array.isArray(rawItems)) {
        throw new Error('Checklist import must include an items array.');
    }

    const items = [];
    const errors = [];

    rawItems.forEach((entry) => {
        if (!entry || typeof entry !== 'object') {
            errors.push('Checklist items must be objects.');
            return;
        }

        const categoryId = (entry.categoryId ?? entry.category_id ?? entry.binId ?? entry.bin_id ?? '').toString();
        if (!allowedCategoryIds.has(categoryId)) {
            errors.push(`Unknown category "${categoryId}".`);
            return;
        }

        const value = typeof entry.value === 'string' ? entry.value : (entry.text ?? '');
        if (!value) {
            errors.push(`Checklist item in category "${categoryId}" is missing text.`);
            return;
        }

        const documentId = parseDocumentId(entry.documentId ?? entry.document_id);
        const startOffset = parseOffset(entry.startOffset ?? entry.start_offset);
        const endOffset = parseOffset(entry.endOffset ?? entry.end_offset);

        if (documentId == null) {
            errors.push(`Checklist item "${value}" is missing documentId.`);
            return;
        }
        if (startOffset == null || endOffset == null || startOffset >= endOffset) {
            errors.push(`Checklist item "${value}" has invalid offsets.`);
            return;
        }

        const doc = documentLookup[documentId];
        if (!doc) {
            errors.push(`Checklist item "${value}" references unknown document ${documentId}.`);
            return;
        }
        if (endOffset > doc.content.length) {
            errors.push(`Checklist item "${value}" has offsets outside document bounds.`);
            return;
        }

        items.push({
            id: typeof entry.id === 'string' && entry.id.trim().length ? entry.id : `local::${crypto.randomUUID()}`,
            categoryId,
            value,
            text: typeof entry.text === 'string' ? entry.text : value,
            documentId,
            startOffset,
            endOffset
        });
    });

    if (errors.length) {
        const suffix = errors.length > 1 ? ` (and ${errors.length - 1} more)` : '';
        throw new Error(`Checklist import failed: ${errors[0]}${suffix}`);
    }

    return items;
};

export const buildCaseStatePayload = ({ caseId, summaryText, prompt, items }) => {
    const normalizedCaseId = String(caseId ?? '').trim();
    if (!normalizedCaseId) {
        throw new Error('Cannot export case state without a case ID.');
    }

    return {
        kind: CASE_STATE_KIND,
        schemaVersion: CASE_STATE_SCHEMA_VERSION,
        exportedAt: new Date().toISOString(),
        caseId: normalizedCaseId,
        summaryText: typeof summaryText === 'string' ? summaryText : '',
        prompt: typeof prompt === 'string' ? prompt : '',
        checklist: {
            items: Array.isArray(items) ? items : []
        }
    };
};

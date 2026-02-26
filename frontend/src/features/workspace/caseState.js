export const CASE_STATE_KIND = 'legal-case-workspace-state';
export const CASE_STATE_SCHEMA_VERSION = 2;

const FALLBACK_CATEGORY_COLORS = [
    '#2D6A4F',
    '#1D4ED8',
    '#B45309',
    '#7C3AED',
    '#BE123C',
    '#0F766E',
    '#4B5563'
];

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

const resolveFallbackCategoryColor = (index) => (
    FALLBACK_CATEGORY_COLORS[index % FALLBACK_CATEGORY_COLORS.length]
);

export const buildDocumentLookup = (documents = []) => {
    const lookup = {};
    documents.forEach((document) => {
        if (document?.id != null) {
            lookup[document.id] = document;
        }
    });
    return lookup;
};

export const normaliseImportedDocuments = (rawDocuments) => {
    if (!Array.isArray(rawDocuments)) {
        throw new Error('Case state import must include a documents array.');
    }

    const documents = [];
    const seenDocumentIds = new Set();

    rawDocuments.forEach((entry) => {
        if (!entry || typeof entry !== 'object') {
            throw new Error('Each imported document must be an object.');
        }

        const documentId = parseDocumentId(entry.id ?? entry.documentId ?? entry.document_id);
        if (documentId == null) {
            throw new Error('Each imported document must include a numeric id.');
        }
        if (seenDocumentIds.has(documentId)) {
            throw new Error(`Imported documents contain duplicate id "${documentId}".`);
        }
        seenDocumentIds.add(documentId);

        const content = entry.content ?? entry.text ?? entry.body;
        if (typeof content !== 'string') {
            throw new Error(`Imported document "${documentId}" must include content as a string.`);
        }

        const titleCandidate = entry.title ?? entry.name;
        const title = typeof titleCandidate === 'string' && titleCandidate.trim().length
            ? titleCandidate.trim()
            : `Document ${documentId}`;

        const type = typeof entry.type === 'string' ? entry.type : '';
        const date = typeof entry.date === 'string' ? entry.date : '';

        documents.push({
            id: documentId,
            title,
            content,
            ...(type ? { type } : {}),
            ...(date ? { date } : {})
        });
    });

    return documents;
};

export const normaliseImportedCategoryMeta = (rawCategories, rawItems = []) => {
    const categoryMap = new Map();

    if (Array.isArray(rawCategories)) {
        rawCategories.forEach((entry) => {
            if (!entry || typeof entry !== 'object') {
                throw new Error('Each checklist category must be an object.');
            }
            const id = (entry.id ?? entry.categoryId ?? entry.category_id ?? '').toString().trim();
            if (!id) {
                throw new Error('Checklist categories must include an id.');
            }
            if (categoryMap.has(id)) {
                throw new Error(`Checklist categories contain duplicate id "${id}".`);
            }
            const labelCandidate = entry.label ?? entry.name;
            const colorCandidate = entry.color;
            categoryMap.set(id, {
                id,
                label: typeof labelCandidate === 'string' && labelCandidate.trim().length ? labelCandidate.trim() : id,
                color: typeof colorCandidate === 'string' && colorCandidate.trim().length
                    ? colorCandidate.trim()
                    : resolveFallbackCategoryColor(categoryMap.size)
            });
        });
    }

    if (Array.isArray(rawItems)) {
        rawItems.forEach((entry) => {
            if (!entry || typeof entry !== 'object') {
                return;
            }
            const categoryId = (entry.categoryId ?? entry.category_id ?? entry.binId ?? entry.bin_id ?? '').toString().trim();
            if (!categoryId || categoryMap.has(categoryId)) {
                return;
            }
            categoryMap.set(categoryId, {
                id: categoryId,
                label: categoryId,
                color: resolveFallbackCategoryColor(categoryMap.size)
            });
        });
    }

    return Array.from(categoryMap.values());
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

    const rawItems = payload.checklist?.items ?? payload.items;
    const documents = normaliseImportedDocuments(payload.documents ?? payload.caseDocuments ?? payload.case_documents);
    const checklistCategories = normaliseImportedCategoryMeta(
        payload.checklist?.categories ?? payload.categories,
        rawItems
    );
    const documentLookup = buildDocumentLookup(documents);
    const allowedCategoryIds = new Set(checklistCategories.map((category) => category.id));
    const items = normaliseImportedItems(rawItems, allowedCategoryIds, documentLookup);

    return {
        caseId,
        summaryText,
        prompt,
        documents,
        checklistCategories,
        items
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

export const buildCaseStatePayload = ({ caseId, summaryText, prompt, items, categories, documents }) => {
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
        documents: Array.isArray(documents) ? documents.map((document) => ({
            id: document.id,
            title: document.title ?? document.name ?? `Document ${document.id}`,
            content: typeof document.content === 'string' ? document.content : '',
            ...(typeof document.type === 'string' && document.type ? { type: document.type } : {}),
            ...(typeof document.date === 'string' && document.date ? { date: document.date } : {})
        })) : [],
        checklist: {
            categories: Array.isArray(categories) ? categories.map((category, index) => ({
                id: category.id,
                label: category.label ?? category.id,
                color: category.color ?? resolveFallbackCategoryColor(index)
            })) : [],
            items: Array.isArray(items) ? items : []
        }
    };
};

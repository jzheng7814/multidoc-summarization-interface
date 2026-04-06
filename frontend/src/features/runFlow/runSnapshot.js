function parseDocumentId(value) {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value;
    }
    if (typeof value === 'string') {
        const parsed = Number.parseInt(value, 10);
        if (!Number.isNaN(parsed)) {
            return parsed;
        }
    }
    return null;
}

function flattenChecklistCategories(categories = []) {
    const output = [];
    (Array.isArray(categories) ? categories : []).forEach((category) => {
        const values = Array.isArray(category?.values) ? category.values : [];
        values.forEach((value) => {
            output.push({
                id: String(value?.id || `value-${output.length + 1}`),
                categoryId: String(category?.id || ''),
                value: String(value?.value ?? value?.text ?? ''),
                text: String(value?.text ?? value?.value ?? ''),
                documentId: parseDocumentId(value?.documentId),
                startOffset: value?.startOffset ?? null,
                endOffset: value?.endOffset ?? null
            });
        });
    });
    return output;
}

export function buildInitialRunCaseState({
    runId,
    documents,
    checklistCategories,
    summaryText = ''
}) {
    return {
        runId: String(runId || '').trim(),
        documents: Array.isArray(documents) ? documents : [],
        checklistCategories: Array.isArray(checklistCategories) ? checklistCategories : [],
        items: flattenChecklistCategories(checklistCategories),
        summaryText: String(summaryText || ''),
        prompt: ''
    };
}

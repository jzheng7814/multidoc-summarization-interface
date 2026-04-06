import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const normaliseRunId = (value) => String(value ?? '').trim();

const coerceDocumentId = (value) => {
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
};

const normaliseDocumentRecord = (document) => {
    const id = coerceDocumentId(document?.id);
    if (id == null) {
        return null;
    }
    return {
        ...document,
        id,
        title: document?.title ?? document?.name ?? `Document ${id}`,
        content: typeof document?.content === 'string' ? document.content : ''
    };
};

const normaliseImportedDocuments = (documents = []) => (
    (Array.isArray(documents) ? documents : [])
        .map((entry) => normaliseDocumentRecord(entry))
        .filter(Boolean)
);

const useDocumentsStore = ({ runId, importedSnapshot = null } = {}) => {
    const hasImportedSnapshot = Boolean(importedSnapshot);
    const initialImportedDocuments = hasImportedSnapshot
        ? normaliseImportedDocuments(importedSnapshot.documents)
        : [];
    const currentRunId = hasImportedSnapshot
        ? normaliseRunId(importedSnapshot.runId)
        : normaliseRunId(runId);

    const [documents] = useState(initialImportedDocuments);
    const [selectedDocument, setSelectedDocument] = useState(initialImportedDocuments[0]?.id ?? null);
    const documentRef = useRef(null);

    useEffect(() => {
        setSelectedDocument((current) => {
            if (current != null && documents.some((doc) => doc.id === current)) {
                return current;
            }
            return documents[0]?.id ?? null;
        });
    }, [documents]);

    const getCurrentDocument = useCallback(() => {
        const doc = documents.find((entry) => entry.id === selectedDocument);
        if (doc) {
            return doc.content;
        }
        if (documents.length === 0) {
            return 'No documents loaded.';
        }
        return 'No document selected';
    }, [documents, selectedDocument]);

    return useMemo(() => ({
        runId: currentRunId,
        documents,
        selectedDocument,
        setSelectedDocument,
        isLoadingDocuments: false,
        documentRef,
        getCurrentDocument
    }), [currentRunId, documents, getCurrentDocument, selectedDocument]);
};

export default useDocumentsStore;

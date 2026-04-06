import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const normaliseCaseId = (value) => String(value ?? '').trim();

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

const useDocumentsStore = ({ caseId, importedSnapshot = null } = {}) => {
    const hasImportedSnapshot = Boolean(importedSnapshot);
    const initialImportedDocuments = hasImportedSnapshot
        ? normaliseImportedDocuments(importedSnapshot.documents)
        : [];
    const initialCaseId = hasImportedSnapshot
        ? normaliseCaseId(importedSnapshot.caseId)
        : normaliseCaseId(caseId);

    const [currentCaseId, setCurrentCaseId] = useState(initialCaseId);
    const [documents, setDocuments] = useState(initialImportedDocuments);
    const [selectedDocument, setSelectedDocument] = useState(initialImportedDocuments[0]?.id ?? null);
    const [lastError, setLastError] = useState(null);
    const [usingImportedSnapshot, setUsingImportedSnapshot] = useState(hasImportedSnapshot);
    const documentRef = useRef(null);

    useEffect(() => {
        if (usingImportedSnapshot) {
            return;
        }
        setCurrentCaseId(normaliseCaseId(caseId));
    }, [caseId, usingImportedSnapshot]);

    useEffect(() => {
        setSelectedDocument((current) => {
            if (current != null && documents.some((doc) => doc.id === current)) {
                return current;
            }
            return documents[0]?.id ?? null;
        });
    }, [documents]);

    const activateImportedSnapshot = useCallback(({ caseId: snapshotCaseId, documents: snapshotDocuments }) => {
        const nextDocuments = normaliseImportedDocuments(snapshotDocuments);
        setCurrentCaseId(normaliseCaseId(snapshotCaseId));
        setDocuments(nextDocuments);
        setLastError(null);
        setUsingImportedSnapshot(true);
        setSelectedDocument(nextDocuments[0]?.id ?? null);
    }, []);

    const loadDocuments = useCallback(async () => {
        const error = new Error('Direct document loading is no longer supported. Load documents through the run setup flow.');
        setLastError(error);
        throw error;
    }, []);

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
        caseId: currentCaseId,
        documents,
        selectedDocument,
        setSelectedDocument,
        isLoadingDocuments: false,
        loadDocuments,
        documentRef,
        getCurrentDocument,
        lastError,
        documentChecklistStatus: documents.length > 0 ? 'ready' : 'empty',
        activateImportedSnapshot
    }), [activateImportedSnapshot, currentCaseId, documents, getCurrentDocument, lastError, loadDocuments, selectedDocument]);
};

export default useDocumentsStore;

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { loadDocuments as loadCaseDocuments } from '../../../services/documentService';
import { fetchChecklistStatus } from '../../../services/apiClient';

const normaliseCaseId = (value) => String(value ?? '').trim();
const ACTIVE_CHECKLIST_STATUSES = new Set(['pending', 'queued', 'preprocessing', 'waiting_resources', 'running', 'finalizing']);

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
    const [remoteDocuments, setRemoteDocuments] = useState(initialImportedDocuments);
    const [selectedDocument, setSelectedDocument] = useState(null);
    const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
    const [lastError, setLastError] = useState(null);
    const [documentChecklistStatus, setDocumentChecklistStatus] = useState(
        hasImportedSnapshot ? (initialImportedDocuments.length > 0 ? 'ready' : 'empty') : 'idle'
    );
    const [usingImportedSnapshot, setUsingImportedSnapshot] = useState(hasImportedSnapshot);
    const documentRef = useRef(null);

    const loadDocuments = useCallback(async (requestedCaseId = currentCaseId) => {
        const resolvedCaseId = normaliseCaseId(requestedCaseId);
        if (!resolvedCaseId) {
            const error = new Error('Case ID is required to load documents.');
            setLastError(error);
            setRemoteDocuments([]);
            setDocumentChecklistStatus('error');
            throw error;
        }
        setIsLoadingDocuments(true);
        setLastError(null);
        setDocumentChecklistStatus('pending');
        setUsingImportedSnapshot(false);

        try {
            const { documents: loadedDocs, checklistStatus } = await loadCaseDocuments(resolvedCaseId);
            const resolvedChecklistStatus = checklistStatus ?? (loadedDocs.length > 0 ? 'ready' : 'empty');
            setRemoteDocuments(loadedDocs);
            setCurrentCaseId(resolvedCaseId);
            setDocumentChecklistStatus(resolvedChecklistStatus);
            return {
                caseId: resolvedCaseId,
                documents: loadedDocs,
                checklistStatus: resolvedChecklistStatus
            };
        } catch (error) {
            console.error('Failed to load documents from backend.', error);
            setRemoteDocuments([]);
            setLastError(error);
            setDocumentChecklistStatus('error');
            throw error;
        } finally {
            setIsLoadingDocuments(false);
        }
    }, [currentCaseId]);

    const activateImportedSnapshot = useCallback(({ caseId: snapshotCaseId, documents }) => {
        const nextCaseId = normaliseCaseId(snapshotCaseId);
        const nextDocuments = normaliseImportedDocuments(documents);
        setCurrentCaseId(nextCaseId);
        setRemoteDocuments(nextDocuments);
        setDocumentChecklistStatus(nextDocuments.length > 0 ? 'ready' : 'empty');
        setLastError(null);
        setIsLoadingDocuments(false);
        setUsingImportedSnapshot(true);
        setSelectedDocument((current) => {
            if (current != null && nextDocuments.some((doc) => doc.id === current)) {
                return current;
            }
            return nextDocuments.length > 0 ? nextDocuments[0].id : null;
        });
    }, []);

    useEffect(() => {
        if (usingImportedSnapshot) {
            return;
        }
        const resolved = normaliseCaseId(caseId);
        setCurrentCaseId(resolved);
    }, [caseId, usingImportedSnapshot]);

    useEffect(() => {
        if (usingImportedSnapshot) {
            return;
        }
        loadDocuments(currentCaseId).catch(() => {});
    }, [currentCaseId, loadDocuments, usingImportedSnapshot]);

    useEffect(() => {
        if (usingImportedSnapshot) {
            return undefined;
        }
        if (!ACTIVE_CHECKLIST_STATUSES.has(documentChecklistStatus)) {
            return undefined;
        }

        let cancelled = false;
        const POLL_INTERVAL_MS = 2000;
        let pollTimeoutId = null;

        const pollForChecklistStatus = async () => {
            try {
                const response = await fetchChecklistStatus(currentCaseId);
                if (cancelled) {
                    return;
                }
                const status = response?.checklistStatus ?? response?.checklist_status ?? 'pending';
                setDocumentChecklistStatus(status || 'pending');
                if (!ACTIVE_CHECKLIST_STATUSES.has(status || 'pending')) {
                    return;
                }
            } catch (error) {
                if (!cancelled) {
                    console.error('Checklist status polling failed', error);
                }
            }

            if (!cancelled) {
                pollTimeoutId = window.setTimeout(pollForChecklistStatus, POLL_INTERVAL_MS);
            }
        };

        pollForChecklistStatus();

        return () => {
            cancelled = true;
            if (pollTimeoutId) {
                window.clearTimeout(pollTimeoutId);
            }
        };
    }, [currentCaseId, documentChecklistStatus, usingImportedSnapshot]);

    useEffect(() => {
        setSelectedDocument((current) => {
            if (current != null && remoteDocuments.some((doc) => doc.id === current)) {
                return current;
            }
            return remoteDocuments.length > 0 ? remoteDocuments[0].id : null;
        });
    }, [remoteDocuments]);

    const getCurrentDocument = useCallback(() => {
        if (isLoadingDocuments) {
            return 'Loading documents...';
        }
        const doc = remoteDocuments.find((d) => d.id === selectedDocument);
        if (doc) {
            return doc.content;
        }
        if (remoteDocuments.length === 0) {
            return lastError
                ? 'Failed to load documents. Please check the case ID and try again.'
                : 'No documents available.';
        }
        return 'No document selected';
    }, [remoteDocuments, isLoadingDocuments, lastError, selectedDocument]);

    const value = useMemo(() => ({
        caseId: currentCaseId,
        documents: remoteDocuments,
        selectedDocument,
        setSelectedDocument,
        isLoadingDocuments,
        loadDocuments,
        documentRef,
        getCurrentDocument,
        lastError,
        documentChecklistStatus,
        activateImportedSnapshot
    }), [
        currentCaseId,
        getCurrentDocument,
        isLoadingDocuments,
        loadDocuments,
        remoteDocuments,
        selectedDocument,
        lastError,
        documentChecklistStatus,
        activateImportedSnapshot
    ]);

    return value;
};

export default useDocumentsStore;

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { loadDocuments as loadCaseDocuments } from '../../../services/documentService';
import { fetchChecklistStatus } from '../../../services/apiClient';

const normaliseCaseId = (value) => String(value ?? '').trim();

const useDocumentsStore = ({ caseId } = {}) => {
    const [currentCaseId, setCurrentCaseId] = useState(normaliseCaseId(caseId));
    const [remoteDocuments, setRemoteDocuments] = useState([]);
    const [selectedDocument, setSelectedDocument] = useState(null);
    const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
    const [lastError, setLastError] = useState(null);
    const [documentChecklistStatus, setDocumentChecklistStatus] = useState('idle');
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

    useEffect(() => {
        const resolved = normaliseCaseId(caseId);
        setCurrentCaseId(resolved);
    }, [caseId]);

    useEffect(() => {
        loadDocuments(currentCaseId).catch(() => {});
    }, [currentCaseId, loadDocuments]);

    useEffect(() => {
        if (documentChecklistStatus !== 'pending') {
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

            if (status && status !== 'pending') {
                setDocumentChecklistStatus(status);
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
    }, [currentCaseId, documentChecklistStatus]);

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
        documentChecklistStatus
    }), [
        currentCaseId,
        getCurrentDocument,
        isLoadingDocuments,
        loadDocuments,
        remoteDocuments,
        selectedDocument,
        lastError,
        documentChecklistStatus
    ]);

    return value;
};

export default useDocumentsStore;

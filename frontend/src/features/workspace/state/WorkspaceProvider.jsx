import React, { createContext, useContext, useMemo } from 'react';
import useDocumentsStore from './useDocumentsStore';
import useSummaryStore from './useSummaryStore';
import useHighlightStore from './useHighlightStore';
import useChecklistStore from './useChecklistStore';

const WorkspaceStateContext = createContext(null);

export const WorkspaceStateProvider = ({ children, caseId, initialCaseState = null }) => {
    const importedDocumentSnapshot = initialCaseState
        ? {
            caseId: initialCaseState.caseId,
            documents: initialCaseState.documents
        }
        : null;
    const documents = useDocumentsStore({ caseId, importedSnapshot: importedDocumentSnapshot });
    const summary = useSummaryStore({
        caseId: documents.caseId,
        initialSummaryText: initialCaseState?.summaryText ?? ''
    });
    const highlight = useHighlightStore({ summary, documents });
    const importedChecklistSnapshot = initialCaseState
        ? {
            categories: initialCaseState.checklistCategories,
            items: initialCaseState.items
        }
        : null;
    const checklist = useChecklistStore({ importedSnapshot: importedChecklistSnapshot });

    const value = useMemo(
        () => ({ documents, summary, highlight, checklist }),
        [documents, summary, highlight, checklist]
    );

    return (
        <WorkspaceStateContext.Provider value={value}>
            {children}
        </WorkspaceStateContext.Provider>
    );
};

const useWorkspaceState = () => {
    const context = useContext(WorkspaceStateContext);
    if (!context) {
        throw new Error('useWorkspaceState must be used within a WorkspaceStateProvider');
    }
    return context;
};

// eslint-disable-next-line react-refresh/only-export-components
export const useDocuments = () => useWorkspaceState().documents;
// eslint-disable-next-line react-refresh/only-export-components
export const useSummary = () => useWorkspaceState().summary;
// eslint-disable-next-line react-refresh/only-export-components
export const useHighlight = () => useWorkspaceState().highlight;
// eslint-disable-next-line react-refresh/only-export-components
export const useChecklist = () => useWorkspaceState().checklist;

export default WorkspaceStateProvider;

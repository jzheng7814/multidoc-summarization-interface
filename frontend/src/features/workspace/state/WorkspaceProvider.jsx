import React, { createContext, useContext, useMemo } from 'react';
import useDocumentsStore from './useDocumentsStore';
import useSummaryStore from './useSummaryStore';
import useHighlightStore from './useHighlightStore';
import useChecklistStore from './useChecklistStore';
import usePromptStore from './usePromptStore';

const WorkspaceStateContext = createContext(null);
const PROMPT_STORE_DISABLED = {
    prompt: '',
    defaultPrompt: '',
    hasCustomPrompt: false,
    isLoading: false,
    error: null,
    savePrompt: () => {},
    clearCustomPrompt: () => {},
    commitPrompt: () => {}
};

export const WorkspaceStateProvider = ({ children, caseId, initialCaseState = null, enablePromptStore = true }) => {
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
    const checklist = useChecklistStore({ caseId: documents.caseId, importedSnapshot: importedChecklistSnapshot });
    const promptStore = usePromptStore({ enabled: enablePromptStore });
    const prompt = enablePromptStore ? promptStore : PROMPT_STORE_DISABLED;

    const value = useMemo(
        () => ({ documents, summary, highlight, checklist, prompt }),
        [documents, summary, highlight, checklist, prompt]
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
// eslint-disable-next-line react-refresh/only-export-components
export const usePrompt = () => useWorkspaceState().prompt;

export default WorkspaceStateProvider;

import React, { useState } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import ThemeToggle from '../../theme/ThemeToggle';

const DOCUMENT_TYPE_OPTIONS = [
    'Complaint',
    'Opinion/Order',
    'Pleading/Motion/Brief',
    'Monitor/Expert/Receiver Report',
    'Settlement',
    'Docket',
    'Correspondence',
    'Declaration/Affidavit',
    'Discovery/FOIA Material',
    'FOIA Request',
    'Internal Memorandum',
    'Legislative Report',
    'Magistrate Report/Recommendation',
    'Statute/Ordinance/Regulation',
    'Executive Order',
    'Transcripts',
    'Justification Memo',
    'Notice Letter',
    'Findings Memo',
    'Other'
];

const createEmptyDraft = () => ({
    file: null,
    name: '',
    date: '',
    type: DOCUMENT_TYPE_OPTIONS[0],
    typeOther: ''
});

const resolveDocumentTypeLabel = (document) => {
    if (document.type === 'Other') {
        return document.typeOther || 'Other';
    }
    return document.type;
};

const HomeScreen = ({
    intakeMode,
    onIntakeModeChange,
    caseId,
    caseIdError,
    onCaseIdChange,
    uploadCaseName,
    onUploadCaseNameChange,
    uploadedDocuments,
    onUploadedDocumentsChange,
    stateFile,
    onStateFileChange,
    isUploading,
    isImportingState,
    onProceed,
    canProceed
}) => {
    const [isAddingDocument, setIsAddingDocument] = useState(false);
    const [draftDocument, setDraftDocument] = useState(createEmptyDraft);
    const [draftError, setDraftError] = useState('');

    const handleStartAddDocument = () => {
        setDraftError('');
        setDraftDocument(createEmptyDraft());
        setIsAddingDocument(true);
    };

    const handleCancelAddDocument = () => {
        setDraftError('');
        setDraftDocument(createEmptyDraft());
        setIsAddingDocument(false);
    };

    const handleAddDocument = () => {
        if (!draftDocument.file) {
            setDraftError('Please upload a .txt file.');
            return;
        }
        if (!draftDocument.file.name.toLowerCase().endsWith('.txt')) {
            setDraftError('Only .txt files are accepted.');
            return;
        }
        if (!draftDocument.name.trim()) {
            setDraftError('Please enter a document name.');
            return;
        }
        if (!draftDocument.date) {
            setDraftError('Please enter a document date.');
            return;
        }
        if (!draftDocument.type) {
            setDraftError('Please select a document type.');
            return;
        }
        if (draftDocument.type === 'Other' && !draftDocument.typeOther.trim()) {
            setDraftError('Please enter a custom document type.');
            return;
        }

        const next = [
            ...uploadedDocuments,
            {
                id: `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`,
                file: draftDocument.file,
                name: draftDocument.name.trim(),
                date: draftDocument.date,
                type: draftDocument.type,
                typeOther: draftDocument.type === 'Other' ? draftDocument.typeOther.trim() : ''
            }
        ];

        onUploadedDocumentsChange(next);
        handleCancelAddDocument();
    };

    const handleRemoveDocument = (documentId) => {
        onUploadedDocumentsChange(uploadedDocuments.filter((doc) => doc.id !== documentId));
    };

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] p-6 text-[var(--color-text-primary)] transition-colors">
            <div className="max-w-4xl mx-auto space-y-6">
                <div className="flex items-center justify-between">
                    <h1 className="text-2xl font-bold">Gavel-Tool: Human-In-The-Loop Legal Case Summarization</h1>
                    <ThemeToggle />
                </div>

                <div className="bg-[var(--color-surface-panel)] rounded-lg shadow-md p-6 border border-[var(--color-border)]">
                    <div className="flex items-center gap-2 mb-4">
                        <button
                            type="button"
                            onClick={() => onIntakeModeChange('caseId')}
                            className={`px-3 py-1.5 text-sm rounded border ${
                                intakeMode === 'caseId'
                                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                                    : 'border-[var(--color-border)] text-[var(--color-text-muted)]'
                            }`}
                        >
                            Case ID
                        </button>
                        <button
                            type="button"
                            onClick={() => onIntakeModeChange('upload')}
                            className={`px-3 py-1.5 text-sm rounded border ${
                                intakeMode === 'upload'
                                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                                    : 'border-[var(--color-border)] text-[var(--color-text-muted)]'
                            }`}
                        >
                            Manual Upload
                        </button>
                        <button
                            type="button"
                            onClick={() => onIntakeModeChange('state')}
                            className={`px-3 py-1.5 text-sm rounded border ${
                                intakeMode === 'state'
                                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                                    : 'border-[var(--color-border)] text-[var(--color-text-muted)]'
                            }`}
                        >
                            Upload Saved Case State
                        </button>
                    </div>

                    {intakeMode === 'caseId' ? (
                        <>
                            <h2 className="text-xl font-semibold mb-4">Enter Case ID</h2>
                            <input
                                type="text"
                                placeholder="Enter Case ID"
                                value={caseId}
                                onChange={(event) => onCaseIdChange(event.target.value)}
                                className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]"
                            />
                        </>
                    ) : intakeMode === 'upload' ? (
                        <>
                            <h2 className="text-xl font-semibold mb-4">Upload Plain Text Documents</h2>

                            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2" htmlFor="upload-case-name">
                                Case Name
                            </label>
                            <input
                                id="upload-case-name"
                                type="text"
                                placeholder="Enter case name"
                                value={uploadCaseName}
                                onChange={(event) => onUploadCaseNameChange(event.target.value)}
                                className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]"
                            />

                            <div className="mt-5 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-3">
                                <div className="mb-2 text-sm font-medium text-[var(--color-text-secondary)]">Documents</div>

                                {uploadedDocuments.length === 0 ? (
                                    <div className="mb-3 rounded border-2 border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface-panel)] px-3 py-6 text-center text-sm text-[var(--color-text-muted)]">
                                        No documents added yet.
                                    </div>
                                ) : (
                                    <div className="mb-3 space-y-2">
                                        {uploadedDocuments.map((document) => (
                                            <div
                                                key={document.id}
                                                className="flex items-start gap-3 rounded border border-[var(--color-border)] bg-[var(--color-surface-panel)] px-3 py-2"
                                            >
                                                <button
                                                    type="button"
                                                    onClick={() => handleRemoveDocument(document.id)}
                                                    className="mt-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-danger)]"
                                                    aria-label={`Remove ${document.name}`}
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                                <div className="min-w-0">
                                                    <div className="text-sm font-semibold text-[var(--color-text-primary)]">{document.name}</div>
                                                    <div className="text-xs text-[var(--color-text-secondary)] mt-0.5">
                                                        {document.date} · {resolveDocumentTypeLabel(document)}
                                                    </div>
                                                    <div className="text-xs text-[var(--color-text-muted)] mt-0.5 truncate">
                                                        {document.file?.name}
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                <button
                                    type="button"
                                    onClick={handleStartAddDocument}
                                    className="w-full flex items-center justify-center gap-2 rounded border-2 border-[var(--color-accent-soft)] bg-[var(--color-surface-panel)] px-3 py-2 text-sm font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)]"
                                >
                                    <Plus className="h-4 w-4" />
                                    Add Document
                                </button>
                            </div>
                        </>
                    ) : (
                        <>
                            <h2 className="text-xl font-semibold mb-4">Upload Saved Case State JSON</h2>
                            <input
                                type="file"
                                accept="application/json,.json"
                                onChange={(event) => onStateFileChange(event.target.files?.[0] || null)}
                                className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)]"
                            />
                            <p className="mt-2 text-xs text-[var(--color-text-muted)]">
                                Import a previously exported full case state (case ID + checklist + summary + prompt).
                            </p>
                            {stateFile && (
                                <div className="mt-3 text-sm text-[var(--color-text-secondary)]">
                                    Selected file: {stateFile.name}
                                </div>
                            )}
                        </>
                    )}

                    {caseIdError && (
                        <p className="mt-2 text-sm text-[var(--color-text-danger)]">{caseIdError}</p>
                    )}
                </div>

                <button
                    onClick={onProceed}
                    disabled={!canProceed}
                    className="w-full bg-[var(--color-accent)] text-[var(--color-text-inverse)] py-3 px-4 rounded-md font-medium hover:bg-[var(--color-accent-hover)] disabled:bg-[var(--color-surface-muted)] disabled:text-[var(--color-input-disabled-text)] disabled:cursor-not-allowed transition-colors"
                >
                    {isUploading ? 'Uploading…' : isImportingState ? 'Importing State…' : 'Continue'}
                </button>
            </div>

            {isAddingDocument && (
                <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
                    <div
                        className="absolute inset-0 bg-[var(--color-overlay-scrim)] backdrop-blur-sm"
                        onClick={handleCancelAddDocument}
                        aria-hidden="true"
                    />
                    <div className="relative w-full max-w-xl rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-2xl p-4">
                        <div className="flex items-center justify-between mb-3">
                            <div className="text-sm font-semibold text-[var(--color-text-primary)]">Add Document</div>
                            <button
                                type="button"
                                onClick={handleCancelAddDocument}
                                className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
                                aria-label="Close add document form"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="space-y-3">
                            <div>
                                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Upload file (.txt)</label>
                                <input
                                    type="file"
                                    accept=".txt,text/plain"
                                    onChange={(event) => {
                                        const file = event.target.files?.[0] || null;
                                        setDraftDocument((current) => ({ ...current, file }));
                                        setDraftError('');
                                    }}
                                    className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)]"
                                />
                            </div>

                            <div>
                                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Document name</label>
                                <input
                                    type="text"
                                    value={draftDocument.name}
                                    onChange={(event) => {
                                        setDraftDocument((current) => ({ ...current, name: event.target.value }));
                                        setDraftError('');
                                    }}
                                    className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)]"
                                />
                            </div>

                            <div>
                                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Document date</label>
                                <input
                                    type="date"
                                    value={draftDocument.date}
                                    onChange={(event) => {
                                        setDraftDocument((current) => ({ ...current, date: event.target.value }));
                                        setDraftError('');
                                    }}
                                    className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)]"
                                />
                            </div>

                            <div>
                                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Document type</label>
                                <select
                                    value={draftDocument.type}
                                    onChange={(event) => {
                                        setDraftDocument((current) => ({
                                            ...current,
                                            type: event.target.value,
                                            typeOther: event.target.value === 'Other' ? current.typeOther : ''
                                        }));
                                        setDraftError('');
                                    }}
                                    className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)]"
                                >
                                    {DOCUMENT_TYPE_OPTIONS.map((option) => (
                                        <option key={option} value={option}>{option}</option>
                                    ))}
                                </select>
                            </div>

                            <div>
                                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Custom type (for Other)</label>
                                <input
                                    type="text"
                                    value={draftDocument.typeOther}
                                    disabled={draftDocument.type !== 'Other'}
                                    onChange={(event) => {
                                        setDraftDocument((current) => ({ ...current, typeOther: event.target.value }));
                                        setDraftError('');
                                    }}
                                    className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)] ${
                                        draftDocument.type === 'Other'
                                            ? 'border-[var(--color-input-border)] bg-[var(--color-input-bg)]'
                                            : 'border-[var(--color-border)] bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]'
                                    }`}
                                />
                            </div>
                        </div>

                        {draftError && (
                            <p className="mt-3 text-xs text-[var(--color-text-danger)]">{draftError}</p>
                        )}

                        <div className="mt-3 flex items-center justify-end gap-2">
                            <button
                                type="button"
                                onClick={handleCancelAddDocument}
                                className="px-3 py-1.5 text-sm rounded border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={handleAddDocument}
                                className="px-3 py-1.5 text-sm rounded bg-[var(--color-accent)] text-[var(--color-text-inverse)] hover:bg-[var(--color-accent-hover)]"
                            >
                                Add Document
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default HomeScreen;

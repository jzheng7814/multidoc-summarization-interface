import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Plus, Trash2, Upload, X } from 'lucide-react';

import { updateRunFromCaseId, updateRunFromUpload } from '../../services/apiClient';

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

function createEmptyDraft() {
    return {
        file: null,
        name: '',
        date: '',
        type: DOCUMENT_TYPE_OPTIONS[0],
        typeOther: ''
    };
}

function createDefaultChecklistItem() {
    return {
        key: `New_Item_${Date.now()}`,
        description: '',
        user_instruction: '',
        constraints: [],
        max_steps: 20,
        reasoning_effort: 'medium'
    };
}

function cleanConstraintLines(rawValue) {
    if (!Array.isArray(rawValue)) {
        return [];
    }
    return rawValue.map((entry) => String(entry || '').trim()).filter(Boolean);
}

function parseExtractionConfig(payload) {
    const focusContext = String(payload?.focus_context ?? payload?.focusContext ?? '').trim();
    if (!focusContext) {
        throw new Error('Extraction config must include non-empty focus_context.');
    }

    const checklistSpec = payload?.checklist_spec ?? payload?.checklistSpec;
    const checklistItems = checklistSpec?.checklist_items ?? checklistSpec?.checklistItems;
    if (!Array.isArray(checklistItems) || !checklistItems.length) {
        throw new Error('Extraction config must include checklist_spec.checklist_items.');
    }

    const normalizedItems = checklistItems.map((item, index) => {
        const key = String(item?.key || '').trim();
        const description = String(item?.description || '').trim();
        const userInstruction = String(item?.user_instruction ?? item?.userInstruction ?? '').trim();
        const reasoningEffort = String(item?.reasoning_effort ?? item?.reasoningEffort ?? '').trim().toLowerCase();
        const maxSteps = Number.parseInt(item?.max_steps ?? item?.maxSteps, 10);
        const constraints = cleanConstraintLines(item?.constraints);

        if (!key || !description || !userInstruction) {
            throw new Error(`Checklist item #${index + 1} is missing required text fields.`);
        }
        if (Number.isNaN(maxSteps) || maxSteps < 1) {
            throw new Error(`Checklist item #${index + 1} has invalid max_steps.`);
        }
        if (!['low', 'medium', 'high'].includes(reasoningEffort)) {
            throw new Error(`Checklist item #${index + 1} has invalid reasoning_effort.`);
        }

        return {
            key,
            description,
            user_instruction: userInstruction,
            constraints,
            max_steps: maxSteps,
            reasoning_effort: reasoningEffort
        };
    });

    return {
        focus_context: focusContext,
        checklist_spec: {
            checklist_items: normalizedItems
        }
    };
}

function parseSummaryConfig(payload) {
    const focusContext = String(payload?.focus_context ?? payload?.focusContext ?? '').trim();
    const reasoningEffort = String(payload?.reasoning_effort ?? payload?.reasoningEffort ?? '').trim().toLowerCase();
    const maxSteps = Number.parseInt(payload?.max_steps ?? payload?.maxSteps, 10);

    if (!focusContext) {
        throw new Error('Summary config must include non-empty focus_context.');
    }
    if (!['low', 'medium', 'high'].includes(reasoningEffort)) {
        throw new Error('Summary config reasoning_effort must be low, medium, or high.');
    }
    if (Number.isNaN(maxSteps) || maxSteps < 1) {
        throw new Error('Summary config max_steps must be >= 1.');
    }

    return {
        focus_context: focusContext,
        reasoning_effort: reasoningEffort,
        max_steps: maxSteps
    };
}

function resolveDocumentTypeLabel(document) {
    if (document.type === 'Other') {
        return document.typeOther || 'Other';
    }
    return document.type;
}

function RunSetupPage({
    runId,
    initialRunData,
    onRunDataUpdated,
    onStartExtraction
}) {
    const [intakeMode, setIntakeMode] = useState('caseId');
    const [caseId, setCaseId] = useState('');
    const [uploadCaseName, setUploadCaseName] = useState('');
    const [uploadedDocuments, setUploadedDocuments] = useState([]);

    const [isAddingDocument, setIsAddingDocument] = useState(false);
    const [draftDocument, setDraftDocument] = useState(createEmptyDraft());
    const [draftError, setDraftError] = useState('');

    const [isCreatingRun, setIsCreatingRun] = useState(false);
    const [isStartingExtraction, setIsStartingExtraction] = useState(false);
    const [loadError, setLoadError] = useState('');
    const [runData, setRunData] = useState(() => initialRunData || null);
    const [extractionConfig, setExtractionConfig] = useState(() => {
        if (!initialRunData) {
            return null;
        }
        return parseExtractionConfig(initialRunData?.extractionConfig ?? initialRunData?.extraction_config);
    });
    const [summaryConfig, setSummaryConfig] = useState(() => {
        if (!initialRunData) {
            return null;
        }
        return parseSummaryConfig(initialRunData?.summaryConfig ?? initialRunData?.summary_config);
    });
    const [extractionConfigError, setExtractionConfigError] = useState('');
    const [summaryConfigError, setSummaryConfigError] = useState('');
    const [editingItemIndex, setEditingItemIndex] = useState(null);

    const extractionFileInputRef = useRef(null);
    const summaryFileInputRef = useRef(null);
    const configuredRunIdRef = useRef(runId);

    const canLoadRun = useMemo(() => {
        if (isCreatingRun) {
            return false;
        }
        if (intakeMode === 'caseId') {
            return caseId.trim().length > 0;
        }
        return uploadCaseName.trim().length > 0 && uploadedDocuments.length > 0;
    }, [isCreatingRun, intakeMode, caseId, uploadCaseName, uploadedDocuments.length]);

    useEffect(() => {
        if (!initialRunData) {
            return;
        }
        const incomingRunId = String(initialRunData?.runId ?? initialRunData?.run_id ?? runId ?? '').trim();
        const isRunChanged = configuredRunIdRef.current !== incomingRunId;
        configuredRunIdRef.current = incomingRunId;

        setRunData(initialRunData);
        if (isRunChanged) {
            setExtractionConfig(parseExtractionConfig(initialRunData?.extractionConfig ?? initialRunData?.extraction_config));
            setSummaryConfig(parseSummaryConfig(initialRunData?.summaryConfig ?? initialRunData?.summary_config));
            setEditingItemIndex(null);
            return;
        }
        setExtractionConfig((current) => (
            current || parseExtractionConfig(initialRunData?.extractionConfig ?? initialRunData?.extraction_config)
        ));
        setSummaryConfig((current) => (
            current || parseSummaryConfig(initialRunData?.summaryConfig ?? initialRunData?.summary_config)
        ));
    }, [initialRunData, runId]);

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

        setUploadedDocuments((current) => ([
            ...current,
            {
                id: `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`,
                file: draftDocument.file,
                name: draftDocument.name.trim(),
                date: draftDocument.date,
                type: draftDocument.type,
                typeOther: draftDocument.type === 'Other' ? draftDocument.typeOther.trim() : ''
            }
        ]));
        handleCancelAddDocument();
    };

    const handleRemoveDocument = (documentId) => {
        setUploadedDocuments((current) => current.filter((doc) => doc.id !== documentId));
    };

    const handleLoadRun = async () => {
        if (!runId) {
            setLoadError('Run ID is missing; cannot load documents into run.');
            return;
        }
        setIsCreatingRun(true);
        setLoadError('');
        setExtractionConfigError('');
        setSummaryConfigError('');
        try {
            const payload = intakeMode === 'caseId'
                ? await updateRunFromCaseId(runId, caseId.trim())
                : await updateRunFromUpload(runId, {
                    caseName: uploadCaseName,
                    documents: uploadedDocuments
                });

            setRunData(payload);
            onRunDataUpdated?.(payload);
            if (!extractionConfig) {
                setExtractionConfig(parseExtractionConfig(payload?.extractionConfig ?? payload?.extraction_config));
            }
            if (!summaryConfig) {
                setSummaryConfig(parseSummaryConfig(payload?.summaryConfig ?? payload?.summary_config));
            }
            setEditingItemIndex(null);
        } catch (error) {
            setLoadError(error.message || 'Failed to load documents into this run.');
        } finally {
            setIsCreatingRun(false);
        }
    };

    const handleExportJson = (payload, filename) => {
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    };

    const handleImportExtractionConfig = async (event) => {
        const file = event.target.files?.[0];
        if (!file) {
            return;
        }
        setExtractionConfigError('');
        try {
            const text = await file.text();
            const parsed = JSON.parse(text);
            setExtractionConfig(parseExtractionConfig(parsed));
        } catch (error) {
            setExtractionConfigError(error.message || 'Failed to import extraction config.');
        } finally {
            event.target.value = '';
        }
    };

    const handleImportSummaryConfig = async (event) => {
        const file = event.target.files?.[0];
        if (!file) {
            return;
        }
        setSummaryConfigError('');
        try {
            const text = await file.text();
            const parsed = JSON.parse(text);
            setSummaryConfig(parseSummaryConfig(parsed));
        } catch (error) {
            setSummaryConfigError(error.message || 'Failed to import summary config.');
        } finally {
            event.target.value = '';
        }
    };

    const handleAddChecklistItem = () => {
        setExtractionConfig((current) => {
            if (!current) {
                return current;
            }
            return {
                ...current,
                checklist_spec: {
                    checklist_items: [...current.checklist_spec.checklist_items, createDefaultChecklistItem()]
                }
            };
        });
    };

    const handleUpdateChecklistItem = (itemIndex, updater) => {
        setExtractionConfig((current) => {
            if (!current) {
                return current;
            }
            const nextItems = current.checklist_spec.checklist_items.map((entry, index) => {
                if (index !== itemIndex) {
                    return entry;
                }
                return updater(entry);
            });
            return {
                ...current,
                checklist_spec: {
                    checklist_items: nextItems
                }
            };
        });
    };

    const handleRemoveChecklistItem = (itemIndex) => {
        setExtractionConfig((current) => {
            if (!current) {
                return current;
            }
            return {
                ...current,
                checklist_spec: {
                    checklist_items: current.checklist_spec.checklist_items.filter((_, index) => index !== itemIndex)
                }
            };
        });
        if (editingItemIndex === itemIndex) {
            setEditingItemIndex(null);
        }
    };

    const handleStartExtraction = async () => {
        if (!runData || !onStartExtraction) {
            return;
        }
        setLoadError('');
        setExtractionConfigError('');
        setSummaryConfigError('');
        setIsStartingExtraction(true);
        try {
            const normalizedExtraction = parseExtractionConfig(extractionConfig || {});
            const normalizedSummary = parseSummaryConfig(summaryConfig || {});
            await onStartExtraction({
                runData,
                extractionConfig: normalizedExtraction,
                summaryConfig: normalizedSummary
            });
        } catch (error) {
            const message = error?.message || 'Failed to start extraction run.';
            if (message.toLowerCase().includes('extraction')) {
                setExtractionConfigError(message);
            } else if (message.toLowerCase().includes('summary')) {
                setSummaryConfigError(message);
            } else {
                setLoadError(message);
            }
        } finally {
            setIsStartingExtraction(false);
        }
    };

    const runDocuments = runData?.documents || [];

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] p-6 text-[var(--color-text-primary)] transition-colors">
            <div className="w-full max-w-[1400px] mx-auto space-y-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h1 className="text-2xl font-bold">Summary Job</h1>
                        <p className="text-sm text-[var(--color-text-muted)] mt-1">
                            Configure document intake, extraction, and summary settings for one run.
                        </p>
                    </div>
                </div>

                <section className="bg-[var(--color-surface-panel)] rounded-lg shadow-md p-6 border border-[var(--color-border)] space-y-4">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                        <h2 className="text-xl font-semibold">Section 1: Upload Documents</h2>
                        {runData && (
                            <div className="text-xs text-[var(--color-text-secondary)] rounded-full border border-[var(--color-border)] px-3 py-1">
                                Run ID: {runData.runId || runData.run_id}
                            </div>
                        )}
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => setIntakeMode('caseId')}
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
                            onClick={() => setIntakeMode('upload')}
                            className={`px-3 py-1.5 text-sm rounded border ${
                                intakeMode === 'upload'
                                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                                    : 'border-[var(--color-border)] text-[var(--color-text-muted)]'
                            }`}
                        >
                            Manual Upload
                        </button>
                    </div>

                    {intakeMode === 'caseId' ? (
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-[var(--color-text-secondary)]" htmlFor="case-id-input">
                                Case ID
                            </label>
                            <input
                                id="case-id-input"
                                type="text"
                                value={caseId}
                                onChange={(event) => setCaseId(event.target.value)}
                                placeholder="Enter case ID"
                                className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                            />
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium text-[var(--color-text-secondary)]" htmlFor="upload-case-name">
                                    Case Name
                                </label>
                                <input
                                    id="upload-case-name"
                                    type="text"
                                    value={uploadCaseName}
                                    onChange={(event) => setUploadCaseName(event.target.value)}
                                    placeholder="Enter case name"
                                    className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                />
                            </div>

                            <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-3">
                                <div className="mb-2 text-sm font-medium text-[var(--color-text-secondary)]">Documents</div>
                                {uploadedDocuments.length === 0 ? (
                                    <div className="mb-3 rounded border-2 border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface-panel)] px-3 py-6 text-center text-sm text-[var(--color-text-muted)]">
                                        No documents added yet.
                                    </div>
                                ) : (
                                    <div className="mb-3 space-y-2">
                                        {uploadedDocuments.map((document) => (
                                            <div key={document.id} className="flex items-start gap-3 rounded border border-[var(--color-border)] bg-[var(--color-surface-panel)] px-3 py-2">
                                                <button
                                                    type="button"
                                                    onClick={() => handleRemoveDocument(document.id)}
                                                    className="mt-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-danger)]"
                                                    aria-label={`Remove ${document.name}`}
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                                <div className="min-w-0">
                                                    <div className="text-sm font-semibold">{document.name}</div>
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
                        </div>
                    )}

                    <button
                        type="button"
                        onClick={handleLoadRun}
                        disabled={!canLoadRun}
                        className="w-full bg-[var(--color-accent)] text-[var(--color-text-inverse)] py-3 px-4 rounded-md font-medium hover:bg-[var(--color-accent-hover)] disabled:bg-[var(--color-surface-muted)] disabled:text-[var(--color-input-disabled-text)] disabled:cursor-not-allowed transition-colors"
                    >
                        {isCreatingRun ? 'Loading Documents Into Run…' : 'Load Documents Into Run'}
                    </button>

                    {loadError && (
                        <p className="text-sm text-[var(--color-text-danger)]">{loadError}</p>
                    )}

                    {runData && (
                        <div className="rounded border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-3 text-sm text-[var(--color-text-secondary)]">
                            <div>Case Title: <span className="font-medium text-[var(--color-text-primary)]">{runData.caseTitle || runData.case_title}</span></div>
                            <div className="mt-1">Documents loaded: {runDocuments.length}</div>
                        </div>
                    )}
                </section>

                <section className="bg-[var(--color-surface-panel)] rounded-lg shadow-md p-6 border border-[var(--color-border)] space-y-4">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                        <h2 className="text-xl font-semibold">Section 2: Edit Extraction Configuration</h2>
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={() => extractionFileInputRef.current?.click()}
                                className="inline-flex items-center gap-2 rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] hover:border-[var(--color-border-strong)] disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Upload className="h-4 w-4" />
                                Import JSON
                            </button>
                            <button
                                type="button"
                                onClick={() => extractionConfig && handleExportJson(extractionConfig, 'extraction_config.json')}
                                disabled={!extractionConfig}
                                className="inline-flex items-center gap-2 rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] hover:border-[var(--color-border-strong)] disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Download className="h-4 w-4" />
                                Export JSON
                            </button>
                        </div>
                    </div>

                    <input
                        ref={extractionFileInputRef}
                        type="file"
                        accept="application/json,.json"
                        className="hidden"
                        onChange={handleImportExtractionConfig}
                    />

                    {!extractionConfig ? (
                        <div className="rounded border border-dashed border-[var(--color-border)] px-4 py-6 text-sm text-[var(--color-text-muted)]">
                            Extraction defaults are unavailable for this run.
                        </div>
                    ) : (
                        <>
                            <div className="space-y-2">
                                <label className="text-sm font-medium text-[var(--color-text-secondary)]">Focus Text</label>
                                <textarea
                                    value={extractionConfig.focus_context}
                                    onChange={(event) => setExtractionConfig((current) => ({ ...current, focus_context: event.target.value }))}
                                    rows={10}
                                    className="w-full rounded-md border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                />
                            </div>

                            <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-4 space-y-3">
                                <div className="flex items-center justify-between gap-2">
                                    <h3 className="text-base font-semibold">Checklist Item Definitions</h3>
                                    <button
                                        type="button"
                                        onClick={handleAddChecklistItem}
                                        className="inline-flex items-center gap-2 rounded border border-[var(--color-accent)] px-3 py-1.5 text-sm text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)]"
                                    >
                                        <Plus className="h-4 w-4" />
                                        Add Item
                                    </button>
                                </div>

                                <div className="space-y-3 max-h-[900px] overflow-auto pr-1">
                                    {extractionConfig.checklist_spec.checklist_items.map((item, index) => {
                                        const isEditing = editingItemIndex === index;
                                        return (
                                            <div key={`${item.key}-${index}`} className="rounded border border-[var(--color-border)] bg-[var(--color-surface-panel)] p-3 space-y-3">
                                                <div className="flex items-center justify-between gap-2 flex-wrap">
                                                    <div className="text-sm font-semibold break-all">{item.key}</div>
                                                    <div className="flex items-center gap-2">
                                                        <button
                                                            type="button"
                                                            onClick={() => setEditingItemIndex(isEditing ? null : index)}
                                                            className="rounded border border-[var(--color-border)] px-2.5 py-1 text-xs text-[var(--color-text-primary)] hover:border-[var(--color-border-strong)]"
                                                        >
                                                            {isEditing ? 'Done' : 'Edit'}
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => handleRemoveChecklistItem(index)}
                                                            className="rounded border border-[var(--color-danger-soft)] px-2.5 py-1 text-xs text-[var(--color-text-danger)] hover:bg-[var(--color-danger-soft)]"
                                                        >
                                                            Remove
                                                        </button>
                                                    </div>
                                                </div>

                                                {isEditing ? (
                                                    <div className="space-y-3">
                                                        <div className="space-y-1">
                                                            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">Key</label>
                                                            <input
                                                                type="text"
                                                                value={item.key}
                                                                onChange={(event) => handleUpdateChecklistItem(index, (current) => ({ ...current, key: event.target.value }))}
                                                                className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                                            />
                                                        </div>
                                                        <div className="space-y-1">
                                                            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">Description</label>
                                                            <textarea
                                                                rows={3}
                                                                value={item.description}
                                                                onChange={(event) => handleUpdateChecklistItem(index, (current) => ({ ...current, description: event.target.value }))}
                                                                className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                                            />
                                                        </div>
                                                        <div className="space-y-1">
                                                            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">User Instruction</label>
                                                            <textarea
                                                                rows={3}
                                                                value={item.user_instruction}
                                                                onChange={(event) => handleUpdateChecklistItem(index, (current) => ({ ...current, user_instruction: event.target.value }))}
                                                                className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                                            />
                                                        </div>
                                                        <div className="space-y-1">
                                                            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">Constraints (one line per constraint)</label>
                                                            <textarea
                                                                rows={5}
                                                                value={(item.constraints || []).join('\n')}
                                                                onChange={(event) => handleUpdateChecklistItem(index, (current) => ({
                                                                    ...current,
                                                                    constraints: event.target.value
                                                                        .split('\n')
                                                                        .map((line) => line.trim())
                                                                        .filter(Boolean)
                                                                }))}
                                                                className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                                            />
                                                        </div>
                                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                            <div className="space-y-1">
                                                                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">Max Steps</label>
                                                                <input
                                                                    type="number"
                                                                    min={1}
                                                                    value={item.max_steps}
                                                                    onChange={(event) => handleUpdateChecklistItem(index, (current) => ({
                                                                        ...current,
                                                                        max_steps: Math.max(1, Number.parseInt(event.target.value || '1', 10))
                                                                    }))}
                                                                    className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                                                />
                                                            </div>
                                                            <div className="space-y-1">
                                                                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">Reasoning Effort</label>
                                                                <select
                                                                    value={item.reasoning_effort}
                                                                    onChange={(event) => handleUpdateChecklistItem(index, (current) => ({ ...current, reasoning_effort: event.target.value }))}
                                                                    className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                                                >
                                                                    <option value="low">low</option>
                                                                    <option value="medium">medium</option>
                                                                    <option value="high">high</option>
                                                                </select>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className="text-xs text-[var(--color-text-secondary)] space-y-1">
                                                        <div className="line-clamp-2">{item.description}</div>
                                                        <div>Reasoning: {item.reasoning_effort} · Max steps: {item.max_steps}</div>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        </>
                    )}

                    {extractionConfigError && (
                        <p className="text-sm text-[var(--color-text-danger)]">{extractionConfigError}</p>
                    )}
                </section>

                <section className="bg-[var(--color-surface-panel)] rounded-lg shadow-md p-6 border border-[var(--color-border)] space-y-4">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                        <h2 className="text-xl font-semibold">Section 3: Edit Summary Configuration</h2>
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={() => summaryFileInputRef.current?.click()}
                                className="inline-flex items-center gap-2 rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] hover:border-[var(--color-border-strong)]"
                            >
                                <Upload className="h-4 w-4" />
                                Import JSON
                            </button>
                            <button
                                type="button"
                                onClick={() => handleExportJson(summaryConfig, 'summary_config.json')}
                                disabled={!summaryConfig}
                                className="inline-flex items-center gap-2 rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] hover:border-[var(--color-border-strong)]"
                            >
                                <Download className="h-4 w-4" />
                                Export JSON
                            </button>
                        </div>
                    </div>

                    <input
                        ref={summaryFileInputRef}
                        type="file"
                        accept="application/json,.json"
                        className="hidden"
                        onChange={handleImportSummaryConfig}
                    />

                    {!summaryConfig ? (
                        <div className="rounded border border-dashed border-[var(--color-border)] px-4 py-6 text-sm text-[var(--color-text-muted)]">
                            Summary defaults are unavailable for this run.
                        </div>
                    ) : (
                        <>
                            <div className="space-y-2">
                                <label className="text-sm font-medium text-[var(--color-text-secondary)]">Focus Text</label>
                                <textarea
                                    rows={8}
                                    value={summaryConfig.focus_context}
                                    onChange={(event) => setSummaryConfig((current) => ({ ...current, focus_context: event.target.value }))}
                                    className="w-full rounded-md border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                />
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-1">
                                    <label className="text-sm font-medium text-[var(--color-text-secondary)]">Reasoning Effort</label>
                                    <select
                                        value={summaryConfig.reasoning_effort}
                                        onChange={(event) => setSummaryConfig((current) => ({ ...current, reasoning_effort: event.target.value }))}
                                        className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                    >
                                        <option value="low">low</option>
                                        <option value="medium">medium</option>
                                        <option value="high">high</option>
                                    </select>
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium text-[var(--color-text-secondary)]">Max Steps</label>
                                    <input
                                        type="number"
                                        min={1}
                                        value={summaryConfig.max_steps}
                                        onChange={(event) => setSummaryConfig((current) => ({
                                            ...current,
                                            max_steps: Math.max(1, Number.parseInt(event.target.value || '1', 10))
                                        }))}
                                        className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                    />
                                </div>
                            </div>
                        </>
                    )}

                    {summaryConfigError && (
                        <p className="text-sm text-[var(--color-text-danger)]">{summaryConfigError}</p>
                    )}
                </section>

                <button
                    type="button"
                    onClick={handleStartExtraction}
                    disabled={
                        !runData ||
                        runDocuments.length === 0 ||
                        !extractionConfig ||
                        !summaryConfig ||
                        isStartingExtraction
                    }
                    className="w-full bg-[var(--color-accent)] text-[var(--color-text-inverse)] py-3 px-4 rounded-md font-medium hover:bg-[var(--color-accent-hover)] disabled:bg-[var(--color-surface-muted)] disabled:text-[var(--color-input-disabled-text)] disabled:cursor-not-allowed"
                >
                    {isStartingExtraction ? 'Starting Extraction…' : 'Start Extraction'}
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

                            {draftDocument.type === 'Other' && (
                                <div>
                                    <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Custom document type</label>
                                    <input
                                        type="text"
                                        value={draftDocument.typeOther}
                                        onChange={(event) => {
                                            setDraftDocument((current) => ({ ...current, typeOther: event.target.value }));
                                            setDraftError('');
                                        }}
                                        className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] text-[var(--color-text-primary)]"
                                    />
                                </div>
                            )}
                        </div>

                        {draftError && (
                            <p className="mt-3 text-sm text-[var(--color-text-danger)]">{draftError}</p>
                        )}

                        <div className="mt-4 flex justify-end gap-2">
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
                                Add
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

export default RunSetupPage;

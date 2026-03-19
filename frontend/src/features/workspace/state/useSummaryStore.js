import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { diffWordsWithSpace } from 'diff';
import { getSummaryJob, startSummaryJob } from '../../../services/apiClient';

const normaliseCaseId = (value) => String(value ?? '').trim();
const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

const toPositiveInteger = (value, defaultValue = 0) => {
    const parsed = typeof value === 'number' ? value : Number.parseInt(value, 10);
    if (!Number.isFinite(parsed) || parsed < 0) {
        return defaultValue;
    }
    return parsed;
};

const normalisePatchPayload = (patch = {}) => ({
    startIndex: toPositiveInteger(patch.startIndex ?? patch.start_index, 0),
    deleteCount: toPositiveInteger(patch.deleteCount ?? patch.delete_count, 0),
    insertText: typeof patch.insertText === 'string'
        ? patch.insertText
        : typeof patch.insert_text === 'string'
            ? patch.insert_text
            : ''
});

const buildWordLevelPatches = (baseSummary = '', nextSummary = '') => {
    const source = baseSummary ?? '';
    const target = nextSummary ?? '';
    if (source === target) {
        return [];
    }
    const segments = diffWordsWithSpace(source, target);
    const patches = [];
    let baseCursor = 0;
    let pendingPatch = null;

    const flushPatch = () => {
        if (pendingPatch && (pendingPatch.deleteCount > 0 || pendingPatch.insertText.length > 0)) {
            const startIndex = Math.max(0, Math.min(pendingPatch.startIndex, source.length));
            patches.push({
                startIndex,
                deleteCount: pendingPatch.deleteCount,
                insertText: pendingPatch.insertText
            });
        }
        pendingPatch = null;
    };

    segments.forEach((segment) => {
        const value = segment.value || '';
        if (!segment.added && !segment.removed) {
            baseCursor += value.length;
            flushPatch();
            return;
        }

        if (!pendingPatch) {
            pendingPatch = {
                startIndex: baseCursor,
                deleteCount: 0,
                insertText: ''
            };
        }

        if (segment.removed) {
            pendingPatch.deleteCount += value.length;
            baseCursor += value.length;
        }

        if (segment.added) {
            pendingPatch.insertText += value;
        }
    });

    flushPatch();

    return patches.filter((patch) => patch.deleteCount > 0 || patch.insertText.length > 0);
};

const applyRawPatchesToBase = (baseSummary = '', patches = []) => {
    if (!patches?.length) {
        return baseSummary ?? '';
    }
    const source = baseSummary ?? '';
    let cursor = 0;
    let output = '';
    patches
        .slice()
        .sort((a, b) => a.startIndex - b.startIndex)
        .forEach((patch) => {
            const boundedStart = Math.max(0, Math.min(patch.startIndex, source.length));
            output += source.slice(cursor, boundedStart);
            output += patch.insertText || '';
            cursor = boundedStart + patch.deleteCount;
        });
    output += source.slice(cursor);
    return output;
};

const resolveFinalSummary = (baseSummary = '', providedSummary, patches = []) => {
    const source = baseSummary ?? '';
    const provided = typeof providedSummary === 'string' ? providedSummary : null;
    if (provided != null && provided !== source) {
        return provided;
    }
    if (patches.length > 0) {
        return applyRawPatchesToBase(source, patches);
    }
    if (provided != null) {
        return provided;
    }
    return source;
};

const applyPatchesToBase = (baseSummary, patches) => {
    if (!baseSummary || !patches?.length) {
        return baseSummary ?? '';
    }
    let cursor = 0;
    let output = '';
    patches.forEach((patch) => {
        const { startIndex, deleteCount, insertText, status } = patch;
        const boundedStart = Math.min(startIndex, baseSummary.length);
        output += baseSummary.slice(cursor, boundedStart);
        if (status === 'applied') {
            output += insertText;
            cursor = boundedStart + deleteCount;
        } else {
            cursor = boundedStart;
        }
    });
    output += baseSummary.slice(cursor);
    return output;
};

const recomputePatchPositions = (baseSummary, patches) => {
    if (!patches) {
        return [];
    }
    let delta = 0;
    return patches.map((patch) => {
        const currentStart = patch.startIndex + delta;
        const appliedLength = patch.status === 'applied'
            ? patch.insertText.length
            : patch.deleteCount;
        const currentEnd = currentStart + appliedLength;
        const nextDelta = patch.status === 'applied'
            ? delta + (patch.insertText.length - patch.deleteCount)
            : delta;
        delta = nextDelta;
        return {
            ...patch,
            currentStart,
            currentEnd
        };
    });
};

const hydratePatchAction = (action) => {
    if (!action) {
        return null;
    }
    return {
        ...action,
        patches: recomputePatchPositions(action.baseSummary, action.patches)
    };
};

const useSummaryStore = ({ caseId } = {}) => {
    const [summaryText, setSummaryTextState] = useState('');
    const [isEditMode, setIsEditMode] = useState(false);
    const [isGeneratingSummary, setIsGeneratingSummary] = useState(false);
    const [summaryJobId, setSummaryJobId] = useState(null);
    const [lastSummaryError, setLastSummaryError] = useState(null);
    const summaryRef = useRef(null);
    const [versionHistory, setVersionHistory] = useState([]);
    const [activeVersionId, setActiveVersionId] = useState(null);
    const [patchAction, setPatchAction] = useState(null);
    const [activePatchId, setActivePatchId] = useState(null);

    const toggleEditMode = useCallback(() => {
        setIsEditMode((previous) => !previous);
    }, []);

    const resolvedCaseId = useMemo(() => normaliseCaseId(caseId), [caseId]);

    const draftSummaryRef = useRef(null);

    const setSummaryText = useCallback((value, options = {}) => {
        const { skipPatchInvalidation = false } = options;
        setActiveVersionId(null);
        draftSummaryRef.current = null;
        setSummaryTextState((previous) => {
            const nextValue = typeof value === 'function' ? value(previous) : value;
            if (!skipPatchInvalidation && nextValue !== previous) {
                setPatchAction((current) => (current && !current.isStale ? { ...current, isStale: true } : current));
                setActivePatchId(null);
            }
            return nextValue;
        });
    }, []);

    const summaryTextRef = useRef('');
    useEffect(() => {
        summaryTextRef.current = summaryText;
    }, [summaryText]);

    const saveCurrentVersion = useCallback(() => {
        const timestamp = new Date();
        const versionId = `${timestamp.getTime().toString()}-${Math.random().toString(36).slice(2, 8)}`;
        const entry = {
            id: versionId,
            savedAt: timestamp.toISOString(),
            summaryText
        };
        setVersionHistory((previous) => [entry, ...previous]);
        setActiveVersionId(versionId);
        draftSummaryRef.current = null;
        return entry;
    }, [summaryText]);

    const selectVersion = useCallback((versionId) => {
        if (!versionId) {
            if (draftSummaryRef.current != null) {
                setSummaryTextState(draftSummaryRef.current);
            }
            draftSummaryRef.current = null;
            setActiveVersionId(null);
            return;
        }

        const targetVersion = versionHistory.find((entry) => entry.id === versionId);
        if (!targetVersion) {
            return;
        }

        if (activeVersionId == null) {
            draftSummaryRef.current = summaryText;
        }

        setActiveVersionId(versionId);
        setSummaryTextState(targetVersion.summaryText);
    }, [activeVersionId, summaryText, versionHistory]);

    const applyAiSummaryUpdate = useCallback((nextSummary, patches = []) => {
        const baseSummary = summaryTextRef.current ?? '';
        const normalisedPatches = Array.isArray(patches)
            ? patches
                .map(normalisePatchPayload)
                .filter((entry) => entry.deleteCount > 0 || entry.insertText.length > 0)
            : [];

        const finalSummary = resolveFinalSummary(baseSummary, nextSummary, normalisedPatches);
        const wordPatches = buildWordLevelPatches(baseSummary, finalSummary);

        if (wordPatches.length === 0) {
            setPatchAction(null);
            setActivePatchId(null);
            setSummaryText(finalSummary ?? '', { skipPatchInvalidation: true });
            return;
        }

        const actionId = `ai-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
        const preparedAction = {
            id: actionId,
            createdAt: new Date().toISOString(),
            baseSummary,
            isStale: false,
            patches: wordPatches.map((patch, index) => ({
                ...patch,
                id: `${actionId}-${index}`,
                deletedText: baseSummary.slice(patch.startIndex, patch.startIndex + patch.deleteCount) || '',
                status: 'applied'
            }))
        };

        setPatchAction(hydratePatchAction(preparedAction));
        setActivePatchId(null);
        setSummaryText(finalSummary ?? '', { skipPatchInvalidation: true });
    }, [setSummaryText]);

    const revertPatch = useCallback((patchId) => {
        setPatchAction((current) => {
            if (!current || current.isStale) {
                return current;
            }
            const index = current.patches.findIndex((patch) => patch.id === patchId);
            if (index === -1 || current.patches[index].status !== 'applied') {
                return current;
            }
            const updated = {
                ...current,
                patches: current.patches.map((patch, idx) =>
                    idx === index ? { ...patch, status: 'reverted' } : patch
                )
            };
            const hydrated = hydratePatchAction(updated);
            const recomposed = applyPatchesToBase(hydrated.baseSummary, hydrated.patches);
            setSummaryText(recomposed, { skipPatchInvalidation: true });
            if (activePatchId === patchId) {
                setActivePatchId(null);
            }
            return hydrated;
        });
    }, [activePatchId, setSummaryText]);

    const revertAllPatches = useCallback(() => {
        setPatchAction((current) => {
            if (!current || current.isStale) {
                return current;
            }
            if (!current.patches.some((patch) => patch.status === 'applied')) {
                return current;
            }
            const updated = {
                ...current,
                patches: current.patches.map((patch) => ({ ...patch, status: 'reverted' }))
            };
            setSummaryText(updated.baseSummary, { skipPatchInvalidation: true });
            setActivePatchId(null);
            return hydratePatchAction(updated);
        });
    }, [setSummaryText]);

    const previewPatch = useCallback((patchId) => {
        if (!patchId) {
            setActivePatchId(null);
            return;
        }
        if (!patchAction || patchAction.isStale) {
            setActivePatchId(null);
            return;
        }
        const exists = patchAction.patches.some(
            (patch) => patch.id === patchId && patch.status === 'applied'
        );
        setActivePatchId(exists ? patchId : null);
    }, [patchAction]);

    const clearPatchPreview = useCallback(() => {
        setActivePatchId(null);
    }, []);

    const dismissPatchAction = useCallback(() => {
        setPatchAction(null);
        setActivePatchId(null);
    }, []);

    useEffect(() => {
        if (!patchAction || patchAction.isStale) {
            setActivePatchId(null);
            return;
        }
        if (activePatchId) {
            const stillExists = patchAction.patches.some(
                (patch) => patch.id === activePatchId && patch.status === 'applied'
            );
            if (!stillExists) {
                setActivePatchId(null);
            }
        }
    }, [activePatchId, patchAction]);

    const generateAISummary = useCallback(async () => {
        const targetCaseId = normaliseCaseId(resolvedCaseId);
        if (!targetCaseId) {
            const error = new Error('Case ID is required before generating a summary.');
            setLastSummaryError(error);
            throw error;
        }

        setIsGeneratingSummary(true);
        setLastSummaryError(null);

        try {
            const startPayload = await startSummaryJob(targetCaseId, {});
            const startedJob = startPayload?.job ?? null;
            const startedJobId = startedJob?.id;
            if (!startedJobId) {
                throw new Error('Summary job did not return a job ID.');
            }
            setSummaryJobId(startedJobId);

            const startedAt = Date.now();
            const maxWaitMs = 60 * 60 * 1000;
            while (true) {
                if (Date.now() - startedAt > maxWaitMs) {
                    throw new Error('Timed out waiting for summary generation.');
                }

                const statusPayload = await getSummaryJob(targetCaseId, startedJobId);
                const job = statusPayload?.job ?? null;
                const status = job?.status;

                if (status === 'succeeded') {
                    const nextSummary = typeof job?.summaryText === 'string'
                        ? job.summaryText
                        : typeof job?.summary_text === 'string'
                            ? job.summary_text
                            : '';
                    applyAiSummaryUpdate(nextSummary);
                    return job;
                }

                if (status === 'failed') {
                    const message = job?.error || 'Summary generation failed.';
                    throw new Error(message);
                }

                await sleep(2000);
            }
        } catch (error) {
            setLastSummaryError(error);
            throw error;
        } finally {
            setIsGeneratingSummary(false);
        }
    }, [applyAiSummaryUpdate, resolvedCaseId]);

    const value = useMemo(() => ({
        summaryText,
        setSummaryText,
        isEditMode,
        setIsEditMode,
        toggleEditMode,
        isGeneratingSummary,
        generateAISummary,
        summaryJobId,
        lastSummaryError,
        summaryRef,
        versionHistory,
        activeVersionId,
        saveCurrentVersion,
        selectVersion,
        patchAction,
        activePatchId,
        applyAiSummaryUpdate,
        revertPatch,
        revertAllPatches,
        previewPatch,
        clearPatchPreview,
        dismissPatchAction,
        caseId: resolvedCaseId
    }), [
        generateAISummary,
        isEditMode,
        isGeneratingSummary,
        lastSummaryError,
        summaryJobId,
        summaryText,
        toggleEditMode,
        versionHistory,
        activeVersionId,
        saveCurrentVersion,
        selectVersion,
        patchAction,
        activePatchId,
        applyAiSummaryUpdate,
        revertPatch,
        revertAllPatches,
        previewPatch,
        clearPatchPreview,
        dismissPatchAction,
        resolvedCaseId,
        setSummaryText
    ]);

    return value;
};

export default useSummaryStore;

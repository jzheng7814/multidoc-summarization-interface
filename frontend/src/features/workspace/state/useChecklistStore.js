import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchChecklist } from '../../../services/apiClient';

const normaliseCaseId = (value) => String(value ?? '').trim();

const requireCaseId = (value) => {
    const trimmed = normaliseCaseId(value);
    if (!trimmed) {
        throw new Error('Case ID is required to fetch checklist data.');
    }
    return trimmed;
};

const parseDocumentId = (value) => {
    if (value == null) {
        return null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
};

const normaliseCategories = (payload) => {
    if (!payload) {
        return [];
    }
    const categories = Array.isArray(payload?.categories) ? payload.categories : [];
    return categories.map((category) => ({
        id: category.id,
        label: category.label,
        color: category.color,
        values: Array.isArray(category.values)
            ? category.values.map((value) => ({
                id: value.id,
                value: value.value ?? '',
                text: value.text ?? value.value ?? '',
                documentId: parseDocumentId(value.documentId ?? value.document_id),
                startOffset: value.startOffset ?? value.start_offset ?? null,
                endOffset: value.endOffset ?? value.end_offset ?? null
            }))
            : []
    }));
};

const flattenCategories = (categories = []) => {
    const items = [];
    categories.forEach((category) => {
        const values = Array.isArray(category.values) ? category.values : [];
        values.forEach((value) => {
            items.push({
                id: value.id,
                categoryId: category.id,
                value: value.value ?? '',
                text: value.text ?? value.value ?? '',
                documentId: parseDocumentId(value.documentId ?? value.document_id),
                startOffset: value.startOffset ?? value.start_offset ?? null,
                endOffset: value.endOffset ?? value.end_offset ?? null
            });
        });
    });
    return items;
};

const buildCategories = (meta = [], items = []) =>
    meta.map((category) => ({
        id: category.id,
        label: category.label,
        color: category.color,
        values: items
            .filter((item) => item.categoryId === category.id)
            .map((item) => ({
                id: item.id,
                value: item.value ?? '',
                text: item.text ?? item.value ?? '',
                documentId: parseDocumentId(item.documentId),
                startOffset: item.startOffset ?? null,
                endOffset: item.endOffset ?? null
            }))
    }));

const buildItemId = () => `local::${crypto.randomUUID()}`;

const normaliseCategoryMeta = (categories = []) => (
    (Array.isArray(categories) ? categories : []).map((category) => ({
        id: category.id,
        label: category.label ?? category.id,
        color: category.color ?? '#4B5563'
    }))
);

const useChecklistStore = ({ caseId, importedSnapshot = null } = {}) => {
    const hasImportedSnapshot = Boolean(importedSnapshot);
    const initialCategoryMeta = hasImportedSnapshot
        ? normaliseCategoryMeta(importedSnapshot.categories)
        : [];
    const initialItems = hasImportedSnapshot && Array.isArray(importedSnapshot.items)
        ? importedSnapshot.items
        : [];

    const [categoryMeta, setCategoryMeta] = useState(initialCategoryMeta);
    const [items, setItems] = useState(initialItems);
    const [isLoading, setIsLoading] = useState(!hasImportedSnapshot);
    const [error, setError] = useState(null);
    const [usingImportedSnapshot, setUsingImportedSnapshot] = useState(hasImportedSnapshot);
    const suppressNextHydrationRef = useRef(false);

    const resolvedCaseId = useMemo(() => normaliseCaseId(caseId), [caseId]);

    const hydrateResponse = useCallback((response) => {
        if (!response) {
            setCategoryMeta([]);
            setItems([]);
            return;
        }
        const categories = normaliseCategories(response);
        setCategoryMeta(categories.map((category) => ({
            id: category.id,
            label: category.label,
            color: category.color
        })));
        setItems(flattenCategories(categories));
    }, []);

    const refreshChecklist = useCallback(async () => {
        if (usingImportedSnapshot) {
            setIsLoading(false);
            return null;
        }
        setIsLoading(true);
        setError(null);
        try {
            const targetCaseId = requireCaseId(resolvedCaseId);
            const response = await fetchChecklist(targetCaseId);
            if (suppressNextHydrationRef.current) {
                suppressNextHydrationRef.current = false;
                return response;
            }
            hydrateResponse(response);
            return response;
        } catch (err) {
            setError(err);
            return null;
        } finally {
            setIsLoading(false);
        }
    }, [hydrateResponse, resolvedCaseId, usingImportedSnapshot]);

    const addItem = useCallback(async (payload) => {
        const trimmedValue = payload?.text?.trim();
        if (!trimmedValue) {
            throw new Error('Checklist text is required.');
        }
        if (!payload?.categoryId) {
            throw new Error('Checklist category is required.');
        }
        const nextItem = {
            id: buildItemId(),
            categoryId: payload.categoryId,
            value: trimmedValue,
            text: trimmedValue,
            documentId: parseDocumentId(payload.documentId),
            startOffset: payload.startOffset ?? null,
            endOffset: payload.endOffset ?? null
        };
        setItems((previous) => [...previous, nextItem]);
        return nextItem;
    }, []);

    const deleteItem = useCallback(async (valueId) => {
        if (!valueId) {
            return null;
        }
        setItems((previous) => previous.filter((item) => item.id !== valueId));
        return valueId;
    }, []);

    const replaceItems = useCallback((nextItems) => {
        setUsingImportedSnapshot(true);
        setIsLoading(false);
        setError(null);
        setItems(Array.isArray(nextItems) ? nextItems : []);
    }, []);

    const activateImportedSnapshot = useCallback(({ categories, items: importedItems }) => {
        setCategoryMeta(normaliseCategoryMeta(categories));
        setItems(Array.isArray(importedItems) ? importedItems : []);
        setIsLoading(false);
        setError(null);
        setUsingImportedSnapshot(true);
    }, []);

    const suppressNextServerHydration = useCallback(() => {
        suppressNextHydrationRef.current = true;
    }, []);

    useEffect(() => {
        if (usingImportedSnapshot) {
            setIsLoading(false);
            return;
        }
        void refreshChecklist();
    }, [refreshChecklist, usingImportedSnapshot]);

    const categories = useMemo(() => buildCategories(categoryMeta, items), [categoryMeta, items]);

    const highlightsByDocument = useMemo(() => {
        const lookup = {};
        categories.forEach((category) => {
            category.values.forEach((value) => {
                if (
                    value.documentId == null ||
                    value.startOffset == null ||
                    value.endOffset == null ||
                    value.endOffset <= value.startOffset
                ) {
                    return;
                }
                const key = value.documentId;
                if (!lookup[key]) {
                    lookup[key] = [];
                }
                lookup[key].push({
                    id: value.id,
                    categoryId: category.id,
                    color: category.color,
                    label: category.label,
                    startOffset: value.startOffset,
                    endOffset: value.endOffset,
                    text: value.text || value.value
                });
            });
        });
        Object.values(lookup).forEach((entries) => {
            entries.sort((a, b) => a.startOffset - b.startOffset || a.endOffset - b.endOffset);
        });
        return lookup;
    }, [categories]);

    return {
        categories,
        items,
        isLoading,
        error,
        refreshChecklist,
        addItem,
        deleteItem,
        replaceItems,
        activateImportedSnapshot,
        suppressNextServerHydration,
        highlightsByDocument
    };
};

export default useChecklistStore;

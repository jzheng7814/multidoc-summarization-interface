import { useCallback, useMemo, useState } from 'react';

const parseDocumentId = (value) => {
    if (value == null) {
        return null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
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

const useChecklistStore = ({ importedSnapshot = null } = {}) => {
    const hasImportedSnapshot = Boolean(importedSnapshot);
    const initialCategoryMeta = hasImportedSnapshot
        ? normaliseCategoryMeta(importedSnapshot.categories)
        : [];
    const initialItems = hasImportedSnapshot && Array.isArray(importedSnapshot.items)
        ? importedSnapshot.items
        : [];

    const [categoryMeta] = useState(initialCategoryMeta);
    const [items, setItems] = useState(initialItems);

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

    const updateItem = useCallback(async (valueId, updater) => {
        if (!valueId || typeof updater !== 'function') {
            return null;
        }
        let updatedItem = null;
        setItems((previous) => previous.map((item) => {
            if (item.id !== valueId) {
                return item;
            }
            const next = updater(item);
            if (!next || typeof next !== 'object') {
                updatedItem = item;
                return item;
            }
            updatedItem = next;
            return next;
        }));
        return updatedItem;
    }, []);

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
        addItem,
        deleteItem,
        updateItem,
        highlightsByDocument
    };
};

export default useChecklistStore;

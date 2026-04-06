export function buildDocumentLookup(documents = []) {
    const lookup = {};
    documents.forEach((document) => {
        if (document?.id != null) {
            lookup[document.id] = document;
        }
    });
    return lookup;
}

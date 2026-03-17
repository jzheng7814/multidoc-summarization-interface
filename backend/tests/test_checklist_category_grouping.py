import unittest

from app.core.config import get_settings
from app.schemas.checklists import EvidenceCollection, EvidenceItem, EvidencePointer
from app.services import checklists
from app.services.cluster_checklist_spec import load_cluster_checklist_spec


class ChecklistCategoryGroupingTests(unittest.TestCase):
    def _expected_order_from_spec(self) -> list[str]:
        settings = get_settings()
        spec = load_cluster_checklist_spec(
            settings.cluster_checklist_spec_path,
            strategy=settings.cluster_checklist_strategy,
        )
        items = spec.get("checklist_items", [])
        return [entry["key"] for entry in items]

    def test_category_metadata_uses_spec_item_order_and_item_ids(self):
        expected_order = self._expected_order_from_spec()

        metadata = checklists.get_category_metadata(include_members=True)
        observed_order = [entry["id"] for entry in metadata]
        observed_labels = [entry["label"] for entry in metadata]
        observed_members = [entry["members"] for entry in metadata]
        observed_colors = [entry["color"] for entry in metadata]

        self.assertEqual(observed_order, expected_order)
        self.assertEqual(observed_labels, expected_order)
        self.assertTrue(
            all(members == [category_id] for members, category_id in zip(observed_members, observed_order))
        )
        self.assertEqual(len(observed_colors), len(set(observed_colors)))

    def test_category_collection_groups_by_item_type_and_keeps_all_categories(self):
        expected_order = self._expected_order_from_spec()
        first_key = expected_order[0]
        second_key = expected_order[1]

        collection = EvidenceCollection(
            items=[
                EvidenceItem(
                    bin_id=first_key,
                    value="alpha",
                    evidence=EvidencePointer(document_id=1001, start_offset=0, end_offset=5, verified=True),
                ),
                EvidenceItem(
                    bin_id=first_key,
                    value="beta",
                    evidence=EvidencePointer(document_id=1001, start_offset=6, end_offset=10, verified=True),
                ),
                EvidenceItem(
                    bin_id=second_key,
                    value="gamma",
                    evidence=EvidencePointer(document_id=1002, start_offset=0, end_offset=5, verified=True),
                ),
            ]
        )

        categorized = checklists.build_category_collection_from_collection(collection)
        ordered_ids = [category.id for category in categorized.categories]
        by_id = {category.id: category for category in categorized.categories}

        self.assertEqual(ordered_ids, expected_order)
        self.assertEqual(len(categorized.categories), len(expected_order))
        self.assertEqual(len(by_id[first_key].values), 2)
        self.assertEqual(len(by_id[second_key].values), 1)

        empty_category_count = sum(1 for category in categorized.categories if len(category.values) == 0)
        self.assertEqual(empty_category_count, len(expected_order) - 2)


if __name__ == "__main__":
    unittest.main()

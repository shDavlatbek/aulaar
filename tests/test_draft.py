import unittest

from aulaar.protocol import evision
from aulaar.ui import draft

from .test_evision import valid_block


class DraftTest(unittest.TestCase):
    def setUp(self):
        self.device = evision.decode_config(valid_block())

    def test_diff_and_apply_round_trip(self):
        edited = draft.apply_changes(self.device, {})
        edited.stages[1].x = 1600
        edited.lighting.color = (1, 2, 3)
        edited.polling_wired = 6
        changes = draft.diff(self.device, edited)
        self.assertEqual(changes, {("stages", 1, "x"): 1600, ("lighting", "color"): (1, 2, 3), ("polling_wired",): 6})
        self.assertEqual(draft.apply_changes(self.device, changes), edited)
        self.assertEqual(draft.labels(changes), ["Device lighting", "Polling rate", "DPI stage 2"])

    def test_apply_does_not_mutate_input(self):
        draft.apply_changes(self.device, {("stages", 0, "x"): 1600})
        self.assertEqual(self.device.stages[0].x, 800)

    def test_pending_survives_device_changes_elsewhere(self):
        changes = {("polling_wired",): 6}
        later = draft.apply_changes(self.device, {("active_stage",): 3})  # DPI button pressed meanwhile
        merged = draft.apply_changes(later, changes)
        self.assertEqual((merged.active_stage, merged.polling_wired), (3, 6))

    def test_prune_drops_applied_changes(self):
        changes = {("polling_wired",): 6, ("lod",): 1}
        applied = draft.apply_changes(self.device, {("polling_wired",): 6})
        self.assertEqual(draft.prune(applied, changes), {("lod",): 1})


if __name__ == "__main__":
    unittest.main()

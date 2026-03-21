import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "frontend" / "js" / "hazard-layers.js").read_text(encoding="utf-8")


class HazardLayersSourceGuardsTest(unittest.TestCase):
    def test_debug_flags_are_disabled_for_normal_runtime(self):
        self.assertIn("const DEBUG_HAZARD_LAYERS = false;", SOURCE)
        self.assertNotIn("const DEBUG_FORCE_VISIBLE = true;", SOURCE)
        self.assertNotIn("map.fitBounds(bounds);", SOURCE)

    def test_toggle_binding_is_guarded_against_duplicate_handlers(self):
        self.assertIn("checkbox.dataset.hazardToggleBound === 'true'", SOURCE)
        self.assertIn("checkbox.dataset.hazardToggleBound = 'true'", SOURCE)

    def test_initialize_binds_handlers_in_single_layer_loop(self):
        self.assertIn("Object.entries(HAZARD_LAYERS).map(async ([layerKey, hazard]) => {", SOURCE)
        self.assertIn("attachHazardToggle(checkbox, layerKey);", SOURCE)

    def test_initialize_does_not_replay_all_checked_states_after_setup(self):
        self.assertNotIn("await setHazardLayerVisibility(layerKey, checkbox.checked);", SOURCE)

    def test_load_hazard_layer_returns_leaflet_layer_without_loading_promise(self):
        self.assertNotIn("hazard.loadingPromise", SOURCE)
        self.assertIn("return hazard.layer;", SOURCE)
        self.assertIn("hazard.layer = L.geoJSON(featureCollection, {", SOURCE)

    def test_flood_and_storm_surge_prefer_vector_tiles_when_martin_is_available(self):
        self.assertIn("function shouldUseVectorTiles(layerKey, hazard) {", SOURCE)
        self.assertIn("layerKey === 'flood_tokyo_max' || layerKey === 'storm_surge_tokyo' || !hazard?.apiUrl;", SOURCE)
        self.assertIn("storm_surge_tokyo: [", SOURCE)
        self.assertIn("tilesetId: 'tokyo_storm_surge'", SOURCE)
        self.assertIn("if (shouldUseVectorTiles(layerKey, hazard)) {", SOURCE)
        self.assertIn("return { layerKey, enabled: true, reason: 'vector-tiles' };", SOURCE)

    def test_set_visibility_has_simple_on_off_branches(self):
        self.assertIn("if (!visible) {", SOURCE)
        self.assertIn("map.removeLayer(hazard.layer);", SOURCE)
        self.assertIn("if (!map.hasLayer(layer)) {", SOURCE)
        self.assertIn("layer.addTo(map);", SOURCE)
        self.assertNotIn("map.fitBounds(hazardBounds.pad(0.02)", SOURCE)


if __name__ == "__main__":
    unittest.main()

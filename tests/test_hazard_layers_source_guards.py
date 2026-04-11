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

    def test_all_managed_hazard_layers_prefer_api(self):
        # shouldUseVectorTiles exists and short-circuits on preferApi
        self.assertIn("function shouldUseVectorTiles(layerKey, hazard) {", SOURCE)
        self.assertIn("if (hazard?.preferApi) {", SOURCE)
        # VECTOR_TILE_SOURCES entries are retained for future tile support
        self.assertIn("storm_surge_tokyo: [", SOURCE)
        self.assertIn("tilesetId: 'tokyo_storm_surge'", SOURCE)
        self.assertIn("flood_tokyo_max: [", SOURCE)
        # Each managed layer must have preferApi: true
        for layer_key, next_key in [
            ("storm_surge_tokyo: {", "storm_surge_kanagawa:"),
            ("flood_tokyo_max: {",   "flood_kanagawa_max:"),
            ("inland_flood_tokyo: {", "landslide_tokyo:"),
        ]:
            start = SOURCE.find(layer_key)
            end   = SOURCE.find(next_key, start)
            self.assertGreater(end, start, f"{layer_key} block not found")
            self.assertIn("preferApi: true", SOURCE[start:end], f"{layer_key} missing preferApi: true")
        # inland_flood_tokyo must also have metaUrl for mapping-aware existence check
        il_start = SOURCE.find("inland_flood_tokyo: {")
        il_end   = SOURCE.find("landslide_tokyo:", il_start)
        self.assertIn("metaUrl:", SOURCE[il_start:il_end])
        # vector tile code path still exists (used when preferApi is absent)
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

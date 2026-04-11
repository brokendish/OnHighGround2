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

    def test_hazard_layer_source_routing(self):
        # shouldUseVectorTiles exists and short-circuits on preferApi
        self.assertIn("function shouldUseVectorTiles(layerKey, hazard) {", SOURCE)
        self.assertIn("if (hazard?.preferApi) {", SOURCE)

        # storm_surge and inland_flood prefer API (GeoJSON)
        for layer_key, next_key in [
            ("storm_surge_tokyo: {", "storm_surge_kanagawa:"),
            ("inland_flood_tokyo: {", "landslide_tokyo:"),
        ]:
            start = SOURCE.find(layer_key)
            end   = SOURCE.find(next_key, start)
            self.assertGreater(end, start, f"{layer_key} block not found")
            self.assertIn("preferApi: true", SOURCE[start:end], f"{layer_key} missing preferApi: true")

        # flood uses vector tiles — no preferApi in flood_tokyo_max block
        fl_start = SOURCE.find("flood_tokyo_max: {")
        fl_end   = SOURCE.find("flood_kanagawa_max:", fl_start)
        self.assertGreater(fl_end, fl_start, "flood_tokyo_max block not found")
        self.assertNotIn("preferApi: true", SOURCE[fl_start:fl_end],
                         "flood_tokyo_max must NOT have preferApi: true (uses vector tiles)")

        # flood VECTOR_TILE_SOURCES: normalized property names
        vts_start = SOURCE.find("flood_tokyo_max: [")
        vts_end   = SOURCE.find("],", vts_start) + 2
        flood_vts = SOURCE[vts_start:vts_end]
        self.assertIn("sourceLayer: 'flood'", flood_vts, "sourceLayer must be 'flood' (normalized)")
        self.assertIn("flood_rank", flood_vts, "colorFn must reference flood_rank (not A31a_205)")
        self.assertNotIn("A31a_205", flood_vts, "A31a_205 is raw field; must not appear in VECTOR_TILE_SOURCES")

        # dynamic tileset ID resolution via metaUrl
        self.assertIn("hazard._activeTilesetId", SOURCE)
        self.assertIn("meta.dataset_id.toLowerCase().replace(/-/g, '_')", SOURCE)

        # inland_flood_tokyo must have metaUrl for mapping-aware existence check
        il_start = SOURCE.find("inland_flood_tokyo: {")
        il_end   = SOURCE.find("landslide_tokyo:", il_start)
        self.assertIn("metaUrl:", SOURCE[il_start:il_end])

        # VECTOR_TILE_SOURCES entries for storm_surge retained
        self.assertIn("storm_surge_tokyo: [", SOURCE)
        self.assertIn("tilesetId: 'tokyo_storm_surge'", SOURCE)

        # vector tile code path used for flood
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

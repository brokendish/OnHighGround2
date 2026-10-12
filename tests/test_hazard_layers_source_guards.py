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

        # inland_flood prefers API (GeoJSON)
        il_start = SOURCE.find("inland_flood_tokyo: {")
        il_end   = SOURCE.find("landslide_tokyo:", il_start)
        self.assertGreater(il_end, il_start, "inland_flood_tokyo block not found")
        self.assertIn("preferApi: true", SOURCE[il_start:il_end], "inland_flood_tokyo missing preferApi: true")

        # storm_surge uses vector tiles (preferApi removed in b9b43c0, 2026-04-12) — no preferApi
        ss_start = SOURCE.find("storm_surge_tokyo: {")
        ss_end   = SOURCE.find("storm_surge_kanagawa:", ss_start)
        self.assertGreater(ss_end, ss_start, "storm_surge_tokyo block not found")
        self.assertNotIn("preferApi: true", SOURCE[ss_start:ss_end],
                         "storm_surge_tokyo must NOT have preferApi: true (uses vector tiles)")

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

        # dynamic tileset ID resolution via metaUrl. Since 88ce04d (2026-09-05) the frontend uses the
        # backend /meta tileset_id / tileset_source_layer (the name Martin actually serves) and keeps the
        # static VECTOR_TILE_SOURCES entry only as the fallback; it no longer derives the ID from dataset_id.
        self.assertIn("hazard._activeTilesetId = activeTilesetId;", SOURCE)
        self.assertIn("activeTilesetId = meta.tileset_id;", SOURCE)
        self.assertIn("activeSourceLayer = meta.tileset_source_layer;", SOURCE)
        self.assertNotIn("meta.dataset_id.toLowerCase().replace(/-/g, '_')", SOURCE)

        # inland_flood_tokyo must have metaUrl for mapping-aware existence check
        il_start = SOURCE.find("inland_flood_tokyo: {")
        il_end   = SOURCE.find("landslide_tokyo:", il_start)
        self.assertIn("metaUrl:", SOURCE[il_start:il_end])

        # VECTOR_TILE_SOURCES entries for storm_surge retained. The static tileset is the dataset tile
        # tokyo_surge_001 (TOKYO-SURGE-001); the legacy tokyo_storm_surge tile was retired in 4e4af1e
        # (data_lake/registry/tile_dispositions.json) and must not come back as a frontend source.
        ss_vts_start = SOURCE.find("storm_surge_tokyo: [")
        self.assertNotEqual(ss_vts_start, -1)
        ss_vts = SOURCE[ss_vts_start:SOURCE.find("],", ss_vts_start) + 2]
        self.assertIn("tilesetId: 'tokyo_surge_001'", ss_vts)
        self.assertIn("sourceLayer: 'storm_surge'", ss_vts)
        self.assertNotIn("tilesetId: 'tokyo_storm_surge'", SOURCE)

        # vector tile code path used for flood
        self.assertIn("if (shouldUseVectorTiles(layerKey, hazard)) {", SOURCE)
        self.assertIn("return { layerKey, enabled: true, reason: 'vector-tiles' };", SOURCE)

    def test_set_visibility_has_simple_on_off_branches(self):
        start = SOURCE.find("async function setHazardLayerVisibility(layerKey, visible) {")
        self.assertNotEqual(start, -1)
        body = SOURCE[start:SOURCE.find("\n}\n", start)]
        self.assertIn("if (!visible) {", body)
        self.assertIn("map.removeLayer(hazard.layer);", body)
        # Since 5d78030 (2026-05-01) the ON branch adds the layer through the zoom band
        # (_applyZoomBandToLayer), which keeps the duplicate-add guard.
        self.assertIn("_applyZoomBandToLayer(hazard, band);", body)
        apply_start = SOURCE.find("function _applyZoomBandToLayer(hazard, band) {")
        self.assertNotEqual(apply_start, -1)
        apply_body = SOURCE[apply_start:SOURCE.find("\n}\n", apply_start)]
        self.assertIn("if (!map.hasLayer(hazard.layer)) {", apply_body)
        self.assertIn("hazard.layer.addTo(map);", apply_body)
        self.assertNotIn("map.fitBounds(hazardBounds.pad(0.02)", SOURCE)


if __name__ == "__main__":
    unittest.main()

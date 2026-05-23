'use strict';

// User-facing names for backend and data-layer identifiers.
const HAZARD_DISPLAY_NAMES = {
    lowland_poor_drainage: '低地・排水困難エリア',
    inland_flood:          '内水浸水エリア',
    pseudo_inland_flood:   '推定内水浸水エリア',
    flood:                 '洪水浸水エリア',
    tsunami:               '津波エリア',
    landslide:             '土砂災害エリア',
    storm_surge:           '高潮エリア',
    earthquake:            '地震',
    fire:                  '大規模火事',
    volcano:               '火山現象',
    urban_flood:           '内水浸水エリア',
    inund:                 '浸水キキクル',
    flood_mesh:            '洪水キキクル',
    land:                  '土砂キキクル',
};

const STATUS_DISPLAY_NAMES = {
    safe:        '安全寄り',
    caution:     '注意',
    danger:      '危険',
    unavailable: '取得不可',
    unknown:     '判定不可',
    loading:     '確認中',
    none:        'なし',
    ok:          '正常',
    error:       '取得失敗',
};

function getHazardDisplayName(id) {
    return HAZARD_DISPLAY_NAMES[id] || '対象ハザード';
}

function getStatusDisplayName(status) {
    return STATUS_DISPLAY_NAMES[status] || '判定不可';
}

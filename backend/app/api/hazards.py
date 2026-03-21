import json
from fastapi import APIRouter, HTTPException

from app.services.hazard_dataset_service import HazardDatasetService


router = APIRouter(prefix="/api/hazards", tags=["hazards"])
hazard_dataset_service = HazardDatasetService()


@router.get("/active")
async def list_active_hazard_datasets():
    try:
        return hazard_dataset_service.list_active_hazard_datasets()
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{hazard_type}/{region_code}/meta")
async def get_active_hazard_meta(hazard_type: str, region_code: str):
    try:
        return hazard_dataset_service.get_active_hazard_meta(hazard_type, region_code)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{hazard_type}/{region_code}")
async def get_active_hazard_geojson(hazard_type: str, region_code: str):
    try:
        return hazard_dataset_service.get_active_hazard_geojson(hazard_type, region_code)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

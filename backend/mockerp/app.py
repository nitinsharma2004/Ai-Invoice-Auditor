from __future__ import annotations


 

import json

from pathlib import Path

from typing import Any


 

from fastapi import FastAPI, HTTPException


 

from backend.app.settings import DATA_ROOT


 

DATA_DIR = DATA_ROOT / "ERP_mockdata"



 

def _load_records(filename: str, key: str) -> dict[str, dict[str, Any]]:

    path = DATA_DIR / filename

    try:

        content = json.loads(path.read_text(encoding="utf-8"))

    except (OSError, json.JSONDecodeError) as exc:

        raise RuntimeError(f"Cannot load ERP data file {path}: {exc}") from exc

    if not isinstance(content, list) or any(not isinstance(row, dict) or not row.get(key) for row in content):

        raise RuntimeError(f"ERP data file {path} must be a list of records with '{key}'.")

    return {str(row[key]).upper(): row for row in content}



 

PURCHASE_ORDERS = _load_records("PO Records.json", "po_number")

VENDORS = _load_records("vendors.json", "vendor_id")

SKUS = _load_records("sku_master.json", "item_code")

app = FastAPI(title="Invoice Auditor Mock ERP", version="1.0.0")



 

@app.get("/health")

def health() -> dict[str, Any]:

    return {"status": "healthy", "purchase_orders": len(PURCHASE_ORDERS), "vendors": len(VENDORS), "skus": len(SKUS)}



 

@app.get("/api/erp/po")

def list_purchase_orders() -> list[dict[str, Any]]:

    return list(PURCHASE_ORDERS.values())



 

@app.get("/api/erp/po/{po_number}")

def get_purchase_order(po_number: str) -> dict[str, Any]:

    if record := PURCHASE_ORDERS.get(po_number.upper()):

        return record

    raise HTTPException(status_code=404, detail="Purchase order not found.")



 

@app.get("/api/erp/vendors")

def list_vendors() -> list[dict[str, Any]]:

    return list(VENDORS.values())



 

@app.get("/api/erp/vendor/{vendor_id}")

def get_vendor(vendor_id: str) -> dict[str, Any]:

    if record := VENDORS.get(vendor_id.upper()):

        return record

    raise HTTPException(status_code=404, detail="Vendor not found.")



 

@app.get("/api/erp/skus")

def list_skus() -> list[dict[str, Any]]:

    return list(SKUS.values())



 

@app.get("/api/erp/sku/{item_code}")

def get_sku(item_code: str) -> dict[str, Any]:

    if record := SKUS.get(item_code.upper()):

        return record

    raise HTTPException(status_code=404, detail="SKU not found.")


 
"""Optional local Python API. Hosted static Site runs the matching JS engine."""
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .engine import plan
from .stochastic import stress

app=FastAPI(title="CivicOps Resilience — synthetic exercise API",version="0.1.0")
SCENARIO=json.loads((Path(__file__).resolve().parents[1]/"data/demo/scenario.json").read_text())


class Request(BaseModel):
    options: dict = Field(default_factory=dict)


@app.get("/health")
def health():
    return {"status":"ok","mode":"synthetic_exercise","dispatch_authorized":False}


@app.post("/plan")
def make_plan(request:Request):
    try:
        return plan(SCENARIO,request.options)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422,str(e)) from e


@app.post("/stress")
def make_stress(request:Request):
    try:
        return stress(SCENARIO,request.options,runs=60)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422,str(e)) from e

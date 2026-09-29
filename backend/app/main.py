"""FastAPI 入口：频谱工作台 REST API（离线简化模型）。"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    AnalysisResult,
    AssignRequest,
    AssignSolution,
    Health,
    Mask,
    MaskIn,
    Scenario,
    ScenarioIn,
)
from .optimizer import assign as run_assign
from .spectrum import analyze as run_analyze
from .storage import get_store

app = FastAPI(
    title="频谱工作台 API",
    description="离线载波频率配置核对：重叠/保护带/掩模尾部检查、"
                "线性域功率汇总、OR-Tools 频率指派。不连接无线电设备。",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 局域网教学环境，纯离线数据
    allow_methods=["*"],
    allow_headers=["*"],
)

store = get_store()


def _masks_by_name() -> dict:
    return {m.name: m for m in store.list_masks()}


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", storage=store.backend)


# ---------------------------------------------------------------------------
# 掩模
# ---------------------------------------------------------------------------
@app.get("/api/masks", response_model=list[Mask])
def list_masks() -> list[Mask]:
    return store.list_masks()


@app.post("/api/masks", response_model=Mask)
def create_mask(m: MaskIn) -> Mask:
    return store.create_mask(m)


@app.get("/api/masks/{name}", response_model=Mask)
def get_mask(name: str) -> Mask:
    m = store.get_mask(name)
    if m is None:
        raise HTTPException(404, f"掩模 {name} 不存在")
    return m


@app.delete("/api/masks/{name}")
def delete_mask(name: str) -> dict:
    if not store.delete_mask(name):
        raise HTTPException(404, f"掩模 {name} 不存在")
    return {"deleted": name}


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------
@app.get("/api/scenarios", response_model=list[Scenario])
def list_scenarios() -> list[Scenario]:
    return store.list_scenarios()


@app.post("/api/scenarios", response_model=Scenario)
def create_scenario(s: ScenarioIn) -> Scenario:
    return store.create_scenario(s)


@app.get("/api/scenarios/{sid}", response_model=Scenario)
def get_scenario(sid: int) -> Scenario:
    s = store.get_scenario(sid)
    if s is None:
        raise HTTPException(404, f"场景 {sid} 不存在")
    return s


@app.delete("/api/scenarios/{sid}")
def delete_scenario(sid: int) -> dict:
    if not store.delete_scenario(sid):
        raise HTTPException(404, f"场景 {sid} 不存在")
    return {"deleted": sid}


# ---------------------------------------------------------------------------
# 分析与求解
# ---------------------------------------------------------------------------
@app.post("/api/scenarios/{sid}/analyze", response_model=AnalysisResult)
def analyze_saved(sid: int) -> AnalysisResult:
    s = store.get_scenario(sid)
    if s is None:
        raise HTTPException(404, f"场景 {sid} 不存在")
    return run_analyze(s, _masks_by_name())


@app.post("/api/analyze", response_model=AnalysisResult)
def analyze_ad_hoc(s: ScenarioIn) -> AnalysisResult:
    """对尚未保存的录入内容直接分析（保存掩模用于解析名称）。"""
    return run_analyze(Scenario(**s.model_dump()), _masks_by_name())


@app.post("/api/assign", response_model=AssignSolution)
def assign_freq(req: AssignRequest) -> AssignSolution:
    return run_assign(req)


@app.post("/api/reset_presets")
def reset_presets() -> dict:
    store.reset_presets()
    return {"status": "presets restored", "storage": store.backend}


# 生产环境：若已构建前端静态包则直接托管（可用 FRONTEND_DIST 指定路径）
_candidates = [
    os.environ.get("FRONTEND_DIST"),
    os.path.join(os.path.dirname(__file__), "..", "static_dist"),
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
]
_dist = next((p for p in _candidates if p and os.path.isdir(p)), None)
if _dist:
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")

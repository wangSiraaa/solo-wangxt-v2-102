# 频谱工作台（Spectrum Workbench）

通信工程教学用的**离线**载波频率配置核对工具：录入少量载波和保护间隔后，
绘制频段与发射掩模尾部，检查频带重叠、保护带不足、掩模尾部越界与频段边缘杂散，
功率在线性域汇总后以 dB 显示，并可用 OR-Tools 自动寻找满足间隔的频率位置。

> ⚠️ 仅为离线简化模型（矩形/折线掩模、几何间隔约束），**不连接任何无线电设备、
> 不生成实际发射指令**。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + Vite + Plotly.js（频段矩形 + 掩模尾部曲线 + 冲突定位标注） |
| 后端 | FastAPI + Pydantic |
| 计算 | SciPy（掩模频偏折线插值）、NumPy（线性域功率） |
| 求解 | OR-Tools CP-SAT（kHz 整数模型，载波对 NoOverlap 间隔约束） |
| 存储 | PostgreSQL（`masks` / `scenarios` / `carriers` 三表，外键级联）；无库时自动降级内存存储 |

## 快速开始

### 方式一：Docker Compose（PostgreSQL + API 同源托管前端）

```bash
docker compose up --build
# 打开 http://localhost:8000
```

### 方式二：本地开发（前后端分离热更新）

```bash
# 后端
cd backend
pip install -r requirements.txt
export DATABASE_URL="postgresql://user:pwd@localhost:5432/spectrum"  # 可选；不设则内存存储
PYTHONPATH=. uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev      # http://localhost:5173 ，/api 代理到 8000
```

### 自检（不依赖服务/数据库）

```bash
cd backend && PYTHONPATH=. python3 scripts/selfcheck.py
```

覆盖：线性域功率求和、四类冲突对定位、三种异极化规则、OR-Tools
可行/最优/不可行/固定载波、单载波越界与杂散、配置校验。

## 核对规则（全部定位到载波或载波对）

| 代码 | 含义 | 级别 |
|---|---|---|
| `OVERLAP` | 两载波标称频段几何重叠（给出重叠 MHz） | error / warning* |
| `GUARD_SHORTAGE` | 频段间隙 < 保护间隔（给出差值） | error / warning* |
| `TAIL_LEAK` | 源载波掩模尾部在受害载波频段入口处的电平高于门限
`max(受害功率−裕度, 底噪)`，**两个方向分别检查**，可区分是谁泄漏给谁 | error / warning* |
| `SPURIOUS_EDGE` | 载波不贴边时，掩模在允许频段边缘电平超过杂散限值 | error |
| `BAND_OUTSIDE` | 载波标称频段越出允许频段 | error |
| `PENDING_ISOLATION` | 异极化（H/V）对且规则为 unknown、几何上又有交互 | warning |
| `CROSSPOL_REUSE` | 异极化且规则 allow：按输入规则放行（记录信息） | info |

\* 仅当异极化复用规则为 `unknown` 时几何冲突降级为 warning（待评估）。
极化 `X`（未指定）不主张极化隔离。

### 异极化复用规则（输入决定）

- `deny`：H/V 也必须满足全部间隔；
- `allow`：已知隔离度足够，异极化载波对跳过间隔检查（可同频复用）；
- `unknown`：隔离度未知，仅给「待评估」告警，不直接判错；
  OR-Tools 此时按最保守策略（仍要求间隔）求解。

### 功率汇总

每载波 `dBm → mW`（`10^(dBm/10)`），**线性求和**后再 `10·log10` 转回 dBm。
界面同时显示 mW 与 dBm，便于核对「不能直接对 dB 相加」。

### OR-Tools 指派

- 频率以 kHz 整数建模；每载波完整落在允许频段内；
- 载波对中心距约束 `|fc_i − fc_j| ≥ (bw_i+bw_j)/2 + guard`（NoOverlap 双向析取）；
- 支持 `fixed` 固定部分载波；目标为总位移最小；
- 无解返回 `INFEASIBLE` 与放宽建议。

## 预置核对用例（启动自动播种）

1. **同带宽不同功率**：4×10 MHz 载波。A(43 dBm)/B(46 dBm) 间隙 0.3 MHz
   → 保护带不足 + 双向尾部越界（B→A 比 A→B 越限更严重，可定位高功率泄漏源）；
   C/D 重叠 2 MHz → 频段重叠。
2. **异极化复用待评估**：H/V 同频与窄间隙对，规则 unknown → 全部 warning。
3. **OR-Tools 拥挤频段重排**：5×10 MHz 载波挤在 60 MHz 内（需 58 MHz），
   求解器输出最优重排，应用后重叠/保护带冲突清零。

## API 摘要

```
GET  /api/health                 存储后端（postgres | memory）
GET/POST/DELETE /api/masks[/{name}]       示例频谱掩模（频偏-衰减折线，JSONB）
GET/POST/DELETE /api/scenarios[/{id}]     场景：频段/保护间隔/规则/载波
POST /api/scenarios/{id}/analyze  已存场景分析
POST /api/analyze                 未保存录入直接分析
POST /api/assign                  OR-Tools 频率指派（可带 fixed）
POST /api/reset_presets           恢复示例数据
GET  /docs                        OpenAPI 交互文档
```

## 目录

```
backend/
  app/models.py     Pydantic 模型
  app/spectrum.py   SciPy 掩模插值 + 冲突检测 + 线性域功率 + 绘图曲线
  app/optimizer.py  OR-Tools CP-SAT 指派
  app/storage.py    PostgreSQL 存储 / 内存降级 / 种子数据
  app/presets.py    示例掩模与三个核对场景
  app/main.py       FastAPI 路由（生产环境同源托管前端 dist）
  scripts/selfcheck.py
frontend/
  src/components/SpectrumPlot.jsx   Plotly 频谱图
  src/components/CarrierTable.jsx   载波录入
  src/components/ConflictList.jsx   冲突列表（点击定位载波）
docker-compose.yml  postgres:16 + 后端多阶段镜像
```

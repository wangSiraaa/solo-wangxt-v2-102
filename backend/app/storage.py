"""存储层：PostgreSQL（规范化表）或内存降级存储。

表结构
------
masks(id, name UNIQUE, points JSONB)
scenarios(id, name, band_start, band_stop, guard_mhz,
          cross_pol_rule, spurious_limit_dbm, tail_threshold_db,
          noise_floor_dbm, default_mask_name)
carriers(id, scenario_id FK, idx, name, fc, bandwidth, power_dbm,
         polarization, mask_name)

DATABASE_URL 环境变量指向 PostgreSQL；连接失败时自动降级为内存存储，
分析/求解等核心功能不受影响（仅重启不持久化）。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

import psycopg2
import psycopg2.extras

from .models import (
    Carrier,
    CrossPolRule,
    Mask,
    MaskIn,
    Polarization,
    Scenario,
    ScenarioIn,
)
from .presets import demo_masks, demo_scenarios

DDL = [
    """
    CREATE TABLE IF NOT EXISTS masks (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        points JSONB NOT NULL DEFAULT '[]'::jsonb
    )""",
    """
    CREATE TABLE IF NOT EXISTS scenarios (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        band_start DOUBLE PRECISION NOT NULL,
        band_stop DOUBLE PRECISION NOT NULL,
        guard_mhz DOUBLE PRECISION NOT NULL DEFAULT 0,
        cross_pol_rule TEXT NOT NULL DEFAULT 'deny',
        spurious_limit_dbm DOUBLE PRECISION NOT NULL DEFAULT -13,
        tail_threshold_db DOUBLE PRECISION NOT NULL DEFAULT 10,
        noise_floor_dbm DOUBLE PRECISION NOT NULL DEFAULT -110,
        default_mask_name TEXT
    )""",
    """
    CREATE TABLE IF NOT EXISTS carriers (
        id SERIAL PRIMARY KEY,
        scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        name TEXT NOT NULL,
        fc DOUBLE PRECISION NOT NULL,
        bandwidth DOUBLE PRECISION NOT NULL,
        power_dbm DOUBLE PRECISION NOT NULL,
        polarization TEXT NOT NULL DEFAULT 'X',
        mask_name TEXT
    )""",
]


class MemoryStore:
    """进程内存储，接口与 PostgresStore 一致，启动时播种示例数据。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._masks: dict[str, dict] = {}
        self._scenarios: dict[int, dict] = {}
        self._sid = 0
        self._mid = 0
        for m in demo_masks():
            self.create_mask(MaskIn(**m))
        for s in demo_scenarios():
            self.create_scenario(ScenarioIn(**s))

    @property
    def backend(self) -> str:
        return "memory"

    # -- masks ------------------------------------------------------------
    def list_masks(self) -> list[Mask]:
        with self._lock:
            return [Mask(id=i + 1, name=m["name"], points=m["points"])
                    for i, m in enumerate(self._masks.values())]

    def create_mask(self, m: MaskIn) -> Mask:
        with self._lock:
            self._masks[m.name] = m.model_dump()
            return self.get_mask(m.name)

    def get_mask(self, name: str) -> Optional[Mask]:
        with self._lock:
            m = self._masks.get(name)
            if not m:
                return None
            idx = list(self._masks).index(name)
            return Mask(id=idx + 1, **m)

    def delete_mask(self, name: str) -> bool:
        with self._lock:
            return self._masks.pop(name, None) is not None

    # -- scenarios --------------------------------------------------------
    def list_scenarios(self) -> list[Scenario]:
        with self._lock:
            return [self._load_scenario(sid) for sid in self._scenarios]

    def create_scenario(self, s: ScenarioIn) -> Scenario:
        with self._lock:
            self._sid += 1
            self._scenarios[self._sid] = s.model_dump()
            return self.get_scenario(self._sid)

    def get_scenario(self, sid: int) -> Optional[Scenario]:
        with self._lock:
            if sid not in self._scenarios:
                return None
            return self._load_scenario(sid)

    def _load_scenario(self, sid: int) -> Scenario:
        d = self._scenarios[sid]
        return Scenario(id=sid, **d)

    def delete_scenario(self, sid: int) -> bool:
        with self._lock:
            return self._scenarios.pop(sid, None) is not None

    def reset_presets(self) -> None:
        with self._lock:
            self.__init__()  # type: ignore[misc]


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        with self._conn() as conn:
            with conn.cursor() as cur:
                for stmt in DDL:
                    cur.execute(stmt)
        self._seed()

    def _conn(self):
        return psycopg2.connect(self.dsn)

    @property
    def backend(self) -> str:
        return "postgres"

    def _seed(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM masks")
                if cur.fetchone()[0] == 0:
                    for m in demo_masks():
                        cur.execute(
                            "INSERT INTO masks(name, points) VALUES (%s,%s)",
                            (m["name"], json.dumps(m["points"])),
                        )
                cur.execute("SELECT count(*) FROM scenarios")
                if cur.fetchone()[0] == 0:
                    for s in demo_scenarios():
                        self._insert_scenario(conn, s)

    @staticmethod
    def _insert_scenario(conn, s: ScenarioIn | dict) -> int:
        d = s.model_dump() if isinstance(s, ScenarioIn) else s
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scenarios(name, band_start, band_stop,
                       guard_mhz, cross_pol_rule, spurious_limit_dbm,
                       tail_threshold_db, noise_floor_dbm, default_mask_name)
                   VALUES (%(name)s,%(band_start)s,%(band_stop)s,%(guard_mhz)s,
                       %(cross_pol_rule)s,%(spurious_limit_dbm)s,
                       %(tail_threshold_db)s,%(noise_floor_dbm)s,
                       %(default_mask_name)s)
                   RETURNING id""",
                d,
            )
            sid = cur.fetchone()[0]
            for i, c in enumerate(d["carriers"]):
                cur.execute(
                    """INSERT INTO carriers(scenario_id, idx, name, fc,
                           bandwidth, power_dbm, polarization, mask_name)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (sid, i, c["name"], c["fc"], c["bandwidth"],
                     c["power_dbm"], c["polarization"], c["mask_name"]),
                )
        return sid

    # -- masks ------------------------------------------------------------
    def list_masks(self) -> list[Mask]:
        with self._conn() as conn, conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, name, points FROM masks ORDER BY name")
            rows = cur.fetchall()
        return [Mask(id=r["id"], name=r["name"], points=r["points"])
                for r in rows]

    def create_mask(self, m: MaskIn) -> Mask:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO masks(name, points) VALUES (%s,%s)
                   ON CONFLICT (name) DO UPDATE
                   SET points = EXCLUDED.points
                   RETURNING id""",
                (m.name, json.dumps([p.model_dump() for p in m.points])),
            )
            mid = cur.fetchone()[0]
        got = self.get_mask(m.name)
        assert got is not None
        got.id = mid
        return got

    def get_mask(self, name: str) -> Optional[Mask]:
        with self._conn() as conn, conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, name, points FROM masks WHERE name=%s",
                        (name,))
            r = cur.fetchone()
        return None if r is None else Mask(
            id=r["id"], name=r["name"], points=r["points"])

    def delete_mask(self, name: str) -> bool:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM masks WHERE name=%s", (name,))
            return cur.rowcount > 0

    # -- scenarios --------------------------------------------------------
    def list_scenarios(self) -> list[Scenario]:
        with self._conn() as conn, conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM scenarios ORDER BY id")
            sids = [r["id"] for r in cur.fetchall()]
        return [s for s in (self.get_scenario(i) for i in sids) if s]

    def create_scenario(self, s: ScenarioIn) -> Scenario:
        with self._conn() as conn:
            sid = self._insert_scenario(conn, s)
        got = self.get_scenario(sid)
        assert got is not None
        return got

    def get_scenario(self, sid: int) -> Optional[Scenario]:
        with self._conn() as conn, conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM scenarios WHERE id=%s", (sid,))
            r = cur.fetchone()
            if not r:
                return None
            cur.execute(
                """SELECT name, fc, bandwidth, power_dbm, polarization,
                          mask_name
                   FROM carriers WHERE scenario_id=%s ORDER BY idx""",
                (sid,),
            )
            crows = cur.fetchall()
        carriers = [Carrier(
            name=c["name"], fc=c["fc"], bandwidth=c["bandwidth"],
            power_dbm=c["power_dbm"],
            polarization=Polarization(c["polarization"]),
            mask_name=c["mask_name"],
        ) for c in crows]
        return Scenario(
            id=r["id"], name=r["name"], band_start=r["band_start"],
            band_stop=r["band_stop"], guard_mhz=r["guard_mhz"],
            cross_pol_rule=CrossPolRule(r["cross_pol_rule"]),
            spurious_limit_dbm=r["spurious_limit_dbm"],
            tail_threshold_db=r["tail_threshold_db"],
            noise_floor_dbm=r["noise_floor_dbm"],
            default_mask_name=r["default_mask_name"],
            carriers=carriers,
        )

    def delete_scenario(self, sid: int) -> bool:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM scenarios WHERE id=%s", (sid,))
            return cur.rowcount > 0

    def reset_presets(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM carriers")
            cur.execute("DELETE FROM scenarios")
            cur.execute("DELETE FROM masks")
            # 演示环境恢复到干净 ID
            cur.execute("ALTER SEQUENCE scenarios_id_seq RESTART WITH 1")
            cur.execute("ALTER SEQUENCE carriers_id_seq RESTART WITH 1")
            cur.execute("ALTER SEQUENCE masks_id_seq RESTART WITH 1")
        self._seed()


def get_store() -> MemoryStore | PostgresStore:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        try:
            store = PostgresStore(dsn)
            print(f"[storage] PostgreSQL 已连接：{dsn.split('@')[-1]}")
            return store
        except Exception as exc:  # noqa: BLE001
            print(f"[storage] PostgreSQL 连接失败，降级内存存储：{exc}")
    store = MemoryStore()
    print("[storage] 使用内存存储（设置 DATABASE_URL 可启用 PostgreSQL）")
    return store

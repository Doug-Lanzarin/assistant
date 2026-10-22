"""Casa inteligente sobre o Home Assistant: resolução de nomes, comandos e verificação."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.core.config import DeviceAlias
from app.core.db import Database, from_json, to_json, utcnow
from app.orchestrator.textnorm import normalize_key

from .client import HAError, HomeAssistantClient

CONTROLLABLE = {"light", "switch", "fan", "climate", "media_player", "cover", "input_boolean", "humidifier",
                "water_heater", "vacuum", "lock", "scene", "script", "automation", "sensor", "binary_sensor",
                "alarm_control_panel", "button"}
SENSITIVE_DOMAINS = {"lock", "alarm_control_panel"}
SENSITIVE_HINTS = re.compile(r"garag|portao|port[aã]o|fechadura|alarme|cofre")

DOMAIN_HINTS = [
    (re.compile(r"\b(luz|luzes|lampada|lampadas|iluminacao|abajur|led)\b"), ["light", "switch"]),
    (re.compile(r"\b(ar|ar condicionado|arcondicionado|climatizador|split|aquecedor)\b"), ["climate"]),
    (re.compile(r"\b(tomada|tomadas|interruptor)\b"), ["switch"]),
    (re.compile(r"\b(ventilador|ventiladores|exaustor)\b"), ["fan", "switch"]),
    (re.compile(r"\b(tv|televisao|televisor|som|caixa de som|musica)\b"), ["media_player", "switch"]),
    (re.compile(r"\b(cortina|cortinas|persiana|persianas|portao|garagem)\b"), ["cover"]),
    (re.compile(r"\b(fechadura|porta)\b"), ["lock"]),
    (re.compile(r"\b(aspirador|robo)\b"), ["vacuum"]),
]


class Ambiguity(Exception):
    def __init__(self, options: list[dict]):
        self.options = options
        super().__init__("Mais de um dispositivo corresponde: " + ", ".join(o["name"] for o in options[:6]))


class HomeService:
    def __init__(self, db: Database, settings_store, secrets, toml_devices: list[DeviceAlias] | None = None,
                 client_factory=None, env=None):
        self.db = db
        self.settings = settings_store
        self.secrets = secrets
        self.toml_devices = toml_devices or []
        self._client_factory = client_factory
        self.env = env
        self.verify_delay = 0.6
        self.verify_attempts = 5

    # -- configuração ---------------------------------------------------------------
    def configured(self) -> bool:
        cfg = self.settings.get("home_assistant")
        url = cfg.get("url") or (self.env.ha_url if self.env else None)
        return bool(url and self._token())

    def _token(self) -> str | None:
        tok = self.secrets.get("ha_token") if self.secrets else None
        return tok or (self.env.ha_token if self.env else None)

    def client(self) -> HomeAssistantClient:
        if self._client_factory:
            return self._client_factory()
        cfg = self.settings.get("home_assistant")
        url = cfg.get("url") or (self.env.ha_url if self.env else None)
        token = self._token()
        if not url or not token:
            raise HAError("Home Assistant não configurado: informe a URL e o token em Configurações → Integrações.")
        return HomeAssistantClient(url, token, cfg.get("timeout_s", 10), cfg.get("verify_ssl", True))

    async def test_connection(self) -> dict[str, Any]:
        c = self.client()
        msg = await c.ping()
        states = await c.states()
        return {"ok": True, "message": msg, "entities": len(states)}

    # -- cache de dispositivos --------------------------------------------------------
    async def sync(self) -> list[dict]:
        c = self.client()
        states = await c.states()
        relevant = [s for s in states if s["entity_id"].split(".")[0] in CONTROLLABLE]
        areas = await c.areas([s["entity_id"] for s in relevant])
        toml = {d.entity_id: d for d in self.toml_devices}
        now = utcnow()
        with self.db.transaction():
            for s in relevant:
                eid = s["entity_id"]
                attrs = s.get("attributes", {})
                existing = self.db.query_one("SELECT aliases, room FROM devices WHERE entity_id=?", (eid,))
                alias_list = from_json(existing["aliases"], []) if existing else []
                room = (existing or {}).get("room") or areas.get(eid)
                name = attrs.get("friendly_name") or eid
                if eid in toml:
                    alias_list = sorted(set(alias_list) | set(toml[eid].aliases))
                    room = toml[eid].room or room
                    name = toml[eid].name or name
                self.db.execute(
                    "INSERT INTO devices(entity_id, name, aliases, room, domain, last_state, attributes, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET name=excluded.name,"
                    " aliases=excluded.aliases, room=excluded.room, last_state=excluded.last_state,"
                    " attributes=excluded.attributes, updated_at=excluded.updated_at",
                    (eid, name, to_json(alias_list), room, eid.split(".")[0], s.get("state"), to_json(attrs), now),
                )
        return self.devices()

    def devices(self, domain: str | None = None) -> list[dict]:
        sql = "SELECT * FROM devices"
        params: tuple = ()
        if domain:
            sql += " WHERE domain=?"
            params = (domain,)
        rows = self.db.query(sql + " ORDER BY room, name", params)
        for r in rows:
            r["aliases"] = from_json(r["aliases"], [])
            r["attributes"] = from_json(r["attributes"], {})
        return rows

    def set_alias(self, entity_id: str, aliases: list[str] | None = None, room: str | None = None, name: str | None = None) -> dict:
        row = self.db.query_one("SELECT * FROM devices WHERE entity_id=?", (entity_id,))
        if not row:
            raise HAError("Dispositivo não encontrado no cache; sincronize primeiro.")
        fields = {}
        if aliases is not None:
            fields["aliases"] = to_json([a.strip() for a in aliases if a.strip()])
        if room is not None:
            fields["room"] = room.strip() or None
        if name is not None and name.strip():
            fields["name"] = name.strip()
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(f"UPDATE devices SET {sets} WHERE entity_id=?", (*fields.values(), entity_id))
        return next(d for d in self.devices() if d["entity_id"] == entity_id)

    async def _ensure_cache(self) -> list[dict]:
        devs = self.devices()
        if not devs and self.configured():
            devs = await self.sync()
        return devs

    # -- resolução de nomes ------------------------------------------------------------
    async def resolve(self, target: str, domains: list[str] | None = None, allow_multiple: bool = False) -> list[dict]:
        devs = await self._ensure_cache()
        if not devs:
            raise HAError("Nenhum dispositivo conhecido. Configure o Home Assistant e sincronize os dispositivos.")
        key = normalize_key(target)
        key = re.sub(r"^(o|a|os|as)\s+", "", key)
        # TCL / ar-condicionado configurado explicitamente
        tcl_entity = self.settings.get("tcl").get("climate_entity")
        hinted: list[str] = []
        for pat, doms in DOMAIN_HINTS:
            if pat.search(key):
                hinted = doms
                break
        doms = domains or hinted or None
        if tcl_entity and doms == ["climate"] and not re.search(r"\b(d[aeo]s?|n[ao])\s+\w+", key):
            match = [d for d in devs if d["entity_id"] == tcl_entity]
            if match:
                return match
        # 1) alias / nome exato
        exact = [d for d in devs if key in {normalize_key(a) for a in d["aliases"]} or key == normalize_key(d["name"])
                 or key == d["entity_id"]]
        if exact:
            return exact if allow_multiple or len(exact) == 1 else self._ambiguous(exact)
        # 2) cômodo + domínio
        rooms = {normalize_key(d["room"]) for d in devs if d.get("room")}
        room = next((r for r in sorted(rooms, key=len, reverse=True) if re.search(rf"\b{re.escape(r)}\b", key)), None)
        cands = devs
        if doms:
            cands = [d for d in cands if d["domain"] in doms]
            primary = [d for d in cands if d["domain"] == doms[0]]
            if primary and len(doms) > 1:
                scoped = [d for d in primary if not room or (d.get("room") and normalize_key(d["room"]) == room)]
                if scoped:
                    cands = primary
        if room:
            cands = [d for d in cands if d.get("room") and normalize_key(d["room"]) == room]
        # 3) nome contém as palavras restantes
        words = [w for w in key.split() if w not in {"da", "do", "de", "das", "dos", "na", "no"} and (not room or w not in room.split())]
        if words and not (doms and room):
            named = [d for d in cands if all(w in normalize_key(d["name"] + " " + " ".join(d["aliases"])) for w in words)]
            if named:
                cands = named
            elif not doms and not room:
                cands = []
        if not cands:
            raise HAError(f"Não encontrei um dispositivo correspondente a '{target}'.")
        plural = bool(re.search(r"\b(luzes|lampadas|tomadas|todas|todos|ventiladores|cortinas|persianas)\b", key))
        if len(cands) > 1 and not (allow_multiple or plural):
            return self._ambiguous(cands)
        return cands

    def _ambiguous(self, options: list[dict]):
        raise Ambiguity([{"entity_id": o["entity_id"], "name": o["name"], "room": o.get("room")} for o in options])

    @staticmethod
    def is_sensitive(dev: dict) -> bool:
        return dev["domain"] in SENSITIVE_DOMAINS or bool(SENSITIVE_HINTS.search(normalize_key(dev["name"])))

    # -- comandos ----------------------------------------------------------------------
    async def _verify(self, c: HomeAssistantClient, entity_id: str, check) -> dict | None:
        for _ in range(self.verify_attempts):
            st = await c.state(entity_id)
            if check(st):
                return st
            await asyncio.sleep(self.verify_delay)
        return None

    async def turn(self, target: str, on: bool) -> dict[str, Any]:
        devs = await self.resolve(target, None)
        c = self.client()
        results = []
        for d in devs:
            dom = d["domain"]
            if dom in {"scene", "script"}:
                service, sdom = "turn_on", dom
            elif dom == "cover":
                service, sdom = ("open_cover" if on else "close_cover"), "cover"
            elif dom == "lock":
                service, sdom = ("unlock" if on else "lock"), "lock"
            elif dom in {"sensor", "binary_sensor"}:
                raise HAError(f"'{d['name']}' é um sensor; não pode ser ligado ou desligado.")
            else:
                service, sdom = ("turn_on" if on else "turn_off"), dom
            await c.call_service(sdom, service, {"entity_id": d["entity_id"]})
            if dom in {"scene", "script"}:
                results.append({"entity_id": d["entity_id"], "name": d["name"], "verified": True, "state": "executado"})
                continue
            expected_off = {"off", "closed", "locked", "idle", "docked"}

            def check(st, on=on, expected_off=expected_off):
                s = st.get("state")
                return (s not in expected_off and s not in {"unavailable", "unknown"}) if on else s in expected_off

            st = await self._verify(c, d["entity_id"], check)
            self._update_cache(d["entity_id"], st)
            results.append({"entity_id": d["entity_id"], "name": d["name"], "verified": st is not None,
                            "state": st.get("state") if st else None})
        return {"results": results, "on": on}

    async def set_temperature(self, target: str, temperature: float, hvac_mode: str | None = None) -> dict[str, Any]:
        devs = await self.resolve(target or "ar condicionado", ["climate"])
        d = devs[0]
        attrs = d.get("attributes") or {}
        lo, hi = attrs.get("min_temp", 16), attrs.get("max_temp", 31)
        if not (lo <= temperature <= hi):
            raise HAError(f"Temperatura fora da faixa permitida pelo aparelho ({lo}–{hi} °C).")
        c = self.client()
        data: dict[str, Any] = {"entity_id": d["entity_id"], "temperature": temperature}
        if hvac_mode:
            data["hvac_mode"] = hvac_mode
        await c.call_service("climate", "set_temperature", data)
        st = await self._verify(
            c, d["entity_id"],
            lambda s: abs(float((s.get("attributes") or {}).get("temperature") or -999) - temperature) < 0.01,
        )
        self._update_cache(d["entity_id"], st)
        return {"entity_id": d["entity_id"], "name": d["name"], "verified": st is not None,
                "state": st.get("state") if st else None,
                "target": (st or {}).get("attributes", {}).get("temperature")}

    async def read(self, target: str) -> dict[str, Any]:
        devs = await self.resolve(target, None, allow_multiple=True)
        c = self.client()
        out = []
        for d in devs[:10]:
            st = await c.state(d["entity_id"])
            self._update_cache(d["entity_id"], st)
            out.append({"entity_id": d["entity_id"], "name": d["name"], "state": st.get("state"),
                        "attributes": st.get("attributes", {})})
        return {"devices": out}

    async def measure(self, target: str, measure: str) -> dict[str, Any]:
        devs = await self._ensure_cache()
        key = normalize_key(target)
        dc = "temperature" if measure.startswith("temp") else "humidity"
        cands = [d for d in devs if d["domain"] == "sensor" and (d.get("attributes") or {}).get("device_class") == dc]
        room_cands = [
            d for d in cands
            if key and ((d.get("room") and normalize_key(d["room"]) in key) or key in normalize_key(d["name"]))
        ]
        c = self.client()
        if room_cands:
            st = await c.state(room_cands[0]["entity_id"])
            unit = (st.get("attributes") or {}).get("unit_of_measurement", "")
            return {"name": room_cands[0]["name"], "value": st.get("state"), "unit": unit, "entity_id": room_cands[0]["entity_id"]}
        if dc == "temperature":
            climates = [d for d in devs if d["domain"] == "climate" and (not key or (d.get("room") and normalize_key(d["room"]) in key))]
            if climates:
                st = await c.state(climates[0]["entity_id"])
                val = (st.get("attributes") or {}).get("current_temperature")
                if val is not None:
                    return {"name": climates[0]["name"], "value": val, "unit": "°C", "entity_id": climates[0]["entity_id"]}
        raise HAError(f"Não encontrei sensor de {measure} para '{target}'.")

    async def run_scene(self, name: str) -> dict[str, Any]:
        devs = await self._ensure_cache()
        key = normalize_key(name)
        cands = [d for d in devs if d["domain"] in {"scene", "script", "automation"} and (
            key == normalize_key(d["name"]) or key in normalize_key(d["name"]) or key in {normalize_key(a) for a in d["aliases"]})]
        if not cands:
            raise HAError(f"Não encontrei cena, script ou automação chamada '{name}'.")
        if len(cands) > 1:
            exact = [d for d in cands if normalize_key(d["name"]) == key]
            if len(exact) != 1:
                self._ambiguous(cands)
            cands = exact
        d = cands[0]
        c = self.client()
        if d["domain"] == "automation":
            await c.call_service("automation", "trigger", {"entity_id": d["entity_id"]})
        else:
            await c.call_service(d["domain"], "turn_on", {"entity_id": d["entity_id"]})
        return {"entity_id": d["entity_id"], "name": d["name"], "domain": d["domain"]}

    def _update_cache(self, entity_id: str, st: dict | None) -> None:
        if st:
            self.db.execute(
                "UPDATE devices SET last_state=?, attributes=?, updated_at=? WHERE entity_id=?",
                (st.get("state"), to_json(st.get("attributes", {})), utcnow(), entity_id),
            )

    async def notify(self, service: str, message: str, data: dict | None = None) -> None:
        """Chama um serviço notify.* (ex.: Alexa Media Player: notify.alexa_media_sala)."""
        if not re.fullmatch(r"notify\.[a-z0-9_]+", service):
            raise HAError("Serviço de notificação inválido (esperado notify.nome).")
        dom, srv = service.split(".", 1)
        payload: dict[str, Any] = {"message": message}
        if data:
            payload["data"] = data
        await self.client().call_service(dom, srv, payload)

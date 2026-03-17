"""Oxigraph layer — immutable knowledge graph + SPARQL queries."""

from __future__ import annotations

import json
from pathlib import Path

import pyoxigraph as ox

ETR = "http://gia.dev/etr#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"

PREFIXES = f"""\
PREFIX etr: <{ETR}>
PREFIX rdf: <{RDF}>
PREFIX rdfs: <{RDFS}>
PREFIX xsd: <{XSD}>
"""


def _iri(local: str) -> ox.NamedNode:
    return ox.NamedNode(f"{ETR}{local}")


def _lit(value, datatype: str | None = None) -> ox.Literal:
    if datatype == "integer":
        return ox.Literal(str(value), datatype=ox.NamedNode(f"{XSD}integer"))
    if datatype == "boolean":
        return ox.Literal(str(value).lower(), datatype=ox.NamedNode(f"{XSD}boolean"))
    return ox.Literal(str(value))


class GameGraph:
    """Wraps an Oxigraph in-memory store with domain-specific SPARQL queries."""

    def __init__(self, store: ox.Store | None = None):
        self.store = store or ox.Store()

    def load_ttl(self, path: str | Path) -> None:
        with open(path, "rb") as f:
            self.store.load(f, "text/turtle", base_iri=ETR)

    def load_characters(self, data: list[dict]) -> None:
        for char in data:
            cid = _iri(f"char_{char['id']}")
            self._add(cid, _iri("rdf_type"), _iri("Character"))
            self._add(cid, _iri("characterDescription"), _lit(char["description"]))
            self._add(cid, _iri("lastStand"), _lit(char["last_stand"]))
            self._add(cid, ox.NamedNode(f"{RDFS}label"), _lit(char["name"]))

            for stat_name, stat_val in char["stats"].items():
                sid = _iri(f"char_{char['id']}_stat_{stat_name}")
                self._add(sid, _iri("rdf_type"), _iri("Stat"))
                self._add(sid, _iri("statName"), _lit(stat_name))
                self._add(sid, _iri("statValue"), _lit(stat_val, "integer"))
                self._add(cid, _iri("hasStat"), sid)

            for i, ab in enumerate(char.get("abilities", [])):
                aid = _iri(f"char_{char['id']}_ability_{i}")
                self._add(aid, _iri("rdf_type"), _iri("Ability"))
                self._add(aid, _iri("abilityName"), _lit(ab["name"]))
                self._add(aid, _iri("abilityDescription"), _lit(ab["description"]))
                self._add(aid, _iri("bloodCost"), _lit(ab.get("cost", 0), "integer"))
                if ab.get("bonus_condition"):
                    self._add(aid, _iri("bonusDiceCondition"), _lit(ab["bonus_condition"]))
                    self._add(aid, _iri("bonusDiceCount"), _lit(ab.get("bonus_dice", 0), "integer"))
                if ab.get("special"):
                    self._add(aid, _iri("specialEffect"), _lit(ab["special"]))
                self._add(cid, _iri("hasAbility"), aid)

            for i, adv in enumerate(char.get("advances", [])):
                advid = _iri(f"char_{char['id']}_advance_{i}")
                self._add(advid, _iri("rdf_type"), _iri("Advance"))
                self._add(advid, _iri("abilityName"), _lit(adv["name"]))
                self._add(advid, _iri("abilityDescription"), _lit(adv["description"]))
                self._add(advid, _iri("bloodCost"), _lit(adv.get("cost", 0), "integer"))
                if adv.get("bonus_condition"):
                    self._add(advid, _iri("bonusDiceCondition"), _lit(adv["bonus_condition"]))
                    self._add(advid, _iri("bonusDiceCount"), _lit(adv.get("bonus_dice", 0), "integer"))
                self._add(cid, _iri("hasAdvance"), advid)

            for i, eq in enumerate(char.get("equipment", [])):
                eid = _iri(f"char_{char['id']}_equip_{i}")
                self._add(eid, _iri("rdf_type"), _iri("Equipment"))
                self._add(eid, _iri("equipmentName"), _lit(eq["name"]))
                self._add(eid, _iri("maxUses"), _lit(eq.get("max_uses", 3), "integer"))
                if eq.get("bonus_condition"):
                    self._add(eid, _iri("bonusDiceCondition"), _lit(eq["bonus_condition"]))
                    self._add(eid, _iri("bonusDiceCount"), _lit(eq.get("bonus_dice", 0), "integer"))
                self._add(cid, _iri("hasStartingEquipment"), eid)

            for cat, inj in char.get("injuries", {}).items():
                iid = _iri(f"char_{char['id']}_injury_{cat.replace('-', '_')}")
                self._add(iid, _iri("rdf_type"), _iri("InjurySlot"))
                self._add(iid, _iri("injuryCategory"), _lit(cat))
                self._add(iid, _iri("minorInjury"), _lit(inj["minor"]))
                self._add(iid, _iri("majorInjury"), _lit(inj["major"]))
                self._add(iid, _iri("majorPenalty"), _lit(inj["major_penalty"]))
                self._add(cid, _iri("hasInjurySlot"), iid)

    def load_enemies(self, data: list[dict]) -> None:
        for enemy in data:
            eid = _iri(f"enemy_{enemy['id']}")
            etype = _iri("Ubermensch") if enemy.get("is_ubermensch") else _iri("Enemy")
            self._add(eid, _iri("rdf_type"), etype)
            self._add(eid, ox.NamedNode(f"{RDFS}label"), _lit(enemy["name"]))
            self._add(eid, _iri("enemyName"), _lit(enemy["name"]))
            self._add(eid, _iri("enemyDescription"), _lit(enemy["description"]))
            self._add(eid, _iri("rating"), _lit(enemy["threat"], "integer"))
            self._add(eid, _iri("attackDice"), _lit(enemy["attack"], "integer"))
            self._add(eid, _iri("challengeRating"), _lit(enemy.get("challenge", 0), "integer"))
            self._add(eid, _iri("isSolo"), _lit(enemy.get("solo", False), "boolean"))
            for rule in enemy.get("special_rules", []):
                self._add(eid, _iri("hasSpecialRule"), _lit(rule))
            for hint in enemy.get("foreshadowing", []):
                self._add(eid, _iri("hasForeshadowing"), _lit(hint))
            if enemy.get("blood_flavour"):
                self._add(eid, _iri("bloodFlavour"), _lit(enemy["blood_flavour"]))

    def load_locations(self, data: list[dict]) -> None:
        sector_map = {1: _iri("sector_1"), 2: _iri("sector_2"), 3: _iri("sector_3")}
        for loc in data:
            lid = _iri(f"loc_{loc['id']}")
            self._add(lid, _iri("rdf_type"), _iri("Location"))
            self._add(lid, ox.NamedNode(f"{RDFS}label"), _lit(loc["name"]))
            self._add(lid, _iri("locationName"), _lit(loc["name"]))
            self._add(lid, _iri("locationDescription"), _lit(loc["description"]))
            self._add(lid, _iri("inSector"), sector_map[loc["sector"]])

            obj = loc["objective"]
            oid = _iri(f"loc_{loc['id']}_objective")
            self._add(oid, _iri("rdf_type"), _iri("Objective"))
            self._add(oid, _iri("objectiveName"), _lit(obj["name"]))
            self._add(oid, _iri("objectiveRating"), _lit(obj["rating"], "integer"))
            self._add(oid, _iri("challengeRating"), _lit(obj.get("challenge", 0), "integer"))
            self._add(lid, _iri("hasObjective"), oid)

            for enemy_id in loc.get("enemies", []):
                self._add(lid, _iri("hasThreat"), _lit(enemy_id))

            for conn_id in loc.get("connections", []):
                self._add(lid, _iri("connectsTo"), _iri(f"loc_{conn_id}"))

            for i, loot in enumerate(loc.get("loot", [])):
                loot_id = _iri(f"loc_{loc['id']}_loot_{i}")
                self._add(loot_id, _iri("rdf_type"), _iri("LootItem"))
                self._add(loot_id, _iri("equipmentName"), _lit(loot["name"]))
                if loot.get("bonus_condition"):
                    self._add(loot_id, _iri("bonusDiceCondition"), _lit(loot["bonus_condition"]))
                    self._add(loot_id, _iri("bonusDiceCount"), _lit(loot.get("bonus_dice", 0), "integer"))
                self._add(loot_id, _iri("maxUses"), _lit(loot.get("max_uses", 3), "integer"))
                self._add(lid, _iri("hasLoot"), loot_id)

    def _add(self, s, p, o) -> None:
        self.store.add(ox.Quad(s, p, o))

    def query(self, sparql: str) -> list[dict]:
        results = []
        query_result = self.store.query(PREFIXES + sparql)
        variables = query_result.variables
        for solution in query_result:
            row = {}
            for var in variables:
                val = solution[var]
                if val is None:
                    continue
                name = var.value  # Variable.value gives the name without '?'
                if isinstance(val, ox.Literal):
                    row[name] = val.value
                elif isinstance(val, ox.NamedNode):
                    row[name] = val.value
                else:
                    row[name] = str(val)
            results.append(row)
        return results

    # --- Convenience Queries ---

    def get_all_characters(self) -> list[dict]:
        return self.query("""
            SELECT ?id ?name ?description ?lastStand WHERE {
                ?id etr:rdf_type etr:Character .
                ?id rdfs:label ?name .
                ?id etr:characterDescription ?description .
                ?id etr:lastStand ?lastStand .
            }
        """)

    def get_character_stats(self, char_id: str) -> dict[str, int]:
        rows = self.query(f"""
            SELECT ?statName ?statValue WHERE {{
                etr:char_{char_id} etr:hasStat ?stat .
                ?stat etr:statName ?statName .
                ?stat etr:statValue ?statValue .
            }}
        """)
        return {r["statName"]: int(r["statValue"]) for r in rows}

    def get_character_abilities(self, char_id: str) -> list[dict]:
        return self.query(f"""
            SELECT ?name ?description ?cost ?bonus ?bonusCount ?special WHERE {{
                etr:char_{char_id} etr:hasAbility ?ab .
                ?ab etr:abilityName ?name .
                ?ab etr:abilityDescription ?description .
                ?ab etr:bloodCost ?cost .
                OPTIONAL {{ ?ab etr:bonusDiceCondition ?bonus . }}
                OPTIONAL {{ ?ab etr:bonusDiceCount ?bonusCount . }}
                OPTIONAL {{ ?ab etr:specialEffect ?special . }}
            }}
        """)

    def get_locations_in_sector(self, sector: int) -> list[dict]:
        return self.query(f"""
            SELECT ?id ?name ?description WHERE {{
                ?id etr:rdf_type etr:Location .
                ?id etr:inSector etr:sector_{sector} .
                ?id etr:locationName ?name .
                ?id etr:locationDescription ?description .
            }}
        """)

    def get_location_connections(self, location_id: str) -> list[dict]:
        return self.query(f"""
            SELECT ?id ?name WHERE {{
                etr:loc_{location_id} etr:connectsTo ?id .
                ?id etr:locationName ?name .
            }}
        """)

    def get_enemy(self, enemy_id: str) -> dict | None:
        rows = self.query(f"""
            SELECT ?name ?description ?rating ?attack ?challenge ?solo WHERE {{
                etr:enemy_{enemy_id} etr:enemyName ?name .
                etr:enemy_{enemy_id} etr:enemyDescription ?description .
                etr:enemy_{enemy_id} etr:rating ?rating .
                etr:enemy_{enemy_id} etr:attackDice ?attack .
                etr:enemy_{enemy_id} etr:challengeRating ?challenge .
                etr:enemy_{enemy_id} etr:isSolo ?solo .
            }}
        """)
        return rows[0] if rows else None

    def get_all_enemies(self) -> list[dict]:
        return self.query("""
            SELECT ?id ?name ?rating ?attack ?challenge WHERE {
                ?id etr:rdf_type ?type .
                FILTER(?type IN (etr:Enemy, etr:Ubermensch))
                ?id etr:enemyName ?name .
                ?id etr:rating ?rating .
                ?id etr:attackDice ?attack .
                ?id etr:challengeRating ?challenge .
            }
        """)

    def get_ubermenschen(self) -> list[dict]:
        return self.query("""
            SELECT ?id ?name ?rating ?attack ?challenge WHERE {
                ?id etr:rdf_type etr:Ubermensch .
                ?id etr:enemyName ?name .
                ?id etr:rating ?rating .
                ?id etr:attackDice ?attack .
                ?id etr:challengeRating ?challenge .
            }
        """)

    def get_rules(self) -> list[dict]:
        return self.query("""
            SELECT ?name ?text WHERE {
                ?r a etr:Rule .
                ?r etr:ruleName ?name .
                ?r etr:ruleText ?text .
            }
        """)

    # --- Decision Records ---

    def load_decisions(self, decisions: list) -> None:
        """Load DecisionRecord objects into the graph for SPARQL querying."""
        for d in decisions:
            did = _iri(f"decision_{d.id}")
            self._add(did, _iri("rdf_type"), _iri("Decision"))
            self._add(did, _iri("sessionId"), _lit(d.session_id))
            self._add(did, _iri("actorId"), _lit(d.actor_id))
            self._add(did, _iri("actorName"), _lit(d.actor_name))
            self._add(did, _iri("actionTaken"), _lit(d.action))
            self._add(did, _iri("resultSummary"), _lit(d.result_summary))
            self._add(did, _iri("phaseBefore"), _lit(d.phase_before))
            self._add(did, _iri("phaseAfter"), _lit(d.phase_after))
            self._add(did, _iri("timestamp"), _lit(d.timestamp))

            if d.llm_narration:
                self._add(did, _iri("llmNarration"), _lit(d.llm_narration))
            if d.llm_turn_context:
                self._add(did, _iri("llmTurnContext"), _lit(d.llm_turn_context))

            for i, alt in enumerate(d.affordances_not_taken):
                self._add(did, _iri("actionNotTaken"), _lit(alt))

            for ev in d.events:
                eid = _iri(f"decision_{d.id}_event_{ev.get('type', 'unknown')}")
                self._add(eid, _iri("rdf_type"), _iri("DecisionEvent"))
                self._add(eid, _iri("eventType"), _lit(ev.get("type", "")))
                self._add(did, _iri("triggeredEvent"), eid)

            # Link to actor
            if d.actor_id != "system":
                self._add(did, _iri("madeBy"), _lit(d.actor_id))

    def get_decisions_by_actor(self, actor_name: str) -> list[dict]:
        return self.query(f"""
            SELECT ?id ?action ?result ?phase_before ?phase_after ?ts WHERE {{
                ?id etr:rdf_type etr:Decision .
                ?id etr:actorName "{actor_name}" .
                ?id etr:actionTaken ?action .
                ?id etr:resultSummary ?result .
                ?id etr:phaseBefore ?phase_before .
                ?id etr:phaseAfter ?phase_after .
                ?id etr:timestamp ?ts .
            }} ORDER BY ?ts
        """)

    def get_actions_not_taken(self, actor_name: str) -> list[dict]:
        """Find what actions an actor chose NOT to do — the roads not taken."""
        return self.query(f"""
            SELECT ?action ?alternative ?ts WHERE {{
                ?id etr:rdf_type etr:Decision .
                ?id etr:actorName "{actor_name}" .
                ?id etr:actionTaken ?action .
                ?id etr:actionNotTaken ?alternative .
                ?id etr:timestamp ?ts .
            }} ORDER BY ?ts
        """)

    def get_decisions_with_events(self, event_type: str) -> list[dict]:
        """Find all decisions that triggered a specific event type."""
        return self.query(f"""
            SELECT ?actor ?action ?result ?ts WHERE {{
                ?id etr:rdf_type etr:Decision .
                ?id etr:actorName ?actor .
                ?id etr:actionTaken ?action .
                ?id etr:resultSummary ?result .
                ?id etr:timestamp ?ts .
                ?id etr:triggeredEvent ?ev .
                ?ev etr:eventType "{event_type}" .
            }} ORDER BY ?ts
        """)

    def get_phase_transitions(self) -> list[dict]:
        """Get all phase transitions across the session."""
        return self.query("""
            SELECT ?actor ?action ?phase_before ?phase_after ?ts WHERE {
                ?id etr:rdf_type etr:Decision .
                ?id etr:actorName ?actor .
                ?id etr:actionTaken ?action .
                ?id etr:phaseBefore ?phase_before .
                ?id etr:phaseAfter ?phase_after .
                ?id etr:timestamp ?ts .
                FILTER(?phase_before != ?phase_after)
            } ORDER BY ?ts
        """)

    def get_location_threats(self, location_id: str) -> list[str]:
        rows = self.query(f"""
            SELECT ?enemyId WHERE {{
                etr:loc_{location_id} etr:hasThreat ?enemyId .
            }}
        """)
        return [r["enemyId"] for r in rows]

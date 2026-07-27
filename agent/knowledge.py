"""Space-domain knowledge base for the retrieval-augmented analyst.

A curated set of knowledge chunks covering conjunction assessment, CDM/ODM
standards, collision probability, maneuver planning, atmospheric drag, OrbitWarden's
validation results, an operator runbook, and the space-sustainability context.
Each chunk has a title, body, and topic tag for retrieval and citation.

This is the analyst's "memory" — when the operator asks a question, the RAG
layer retrieves the most relevant chunks and the agent answers with grounded,
citable expertise instead of generic prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeChunk:
    """A unit of retrievable knowledge."""

    chunk_id: str
    title: str
    topic: str
    body: str

    def as_text(self) -> str:
        """The text that gets embedded and shown to the agent."""
        return f"{self.title}\n\n{self.body}"


KNOWLEDGE_BASE: list[KnowledgeChunk] = [
    KnowledgeChunk(
        chunk_id="ca-001",
        title="Conjunction assessment workflow",
        topic="conjunction-assessment",
        body=(
            "Conjunction assessment is the process of predicting close approaches "
            "between a spacecraft and other tracked objects, and deciding whether "
            "action is needed. The standard workflow: (1) screen the catalog over a "
            "look-ahead window (typically 3-7 days); (2) compute the time of closest "
            "approach (TCA) and miss distance for each candidate; (3) compute the "
            "collision probability (Pc); (4) triage against screening thresholds; "
            "(5) for events above threshold, plan and execute an avoidance maneuver. "
            "Operational centers (NASA CARA, the 18th Space Defense Squadron, ESA SSA) "
            "use high-precision ephemerides; smaller operators rely on TLE-based "
            "screening (SGP4), which is fast but less precise."
        ),
    ),
    KnowledgeChunk(
        chunk_id="ca-002",
        title="Screening thresholds and triage",
        topic="conjunction-assessment",
        body=(
            "Operators triage conjunctions using screening volumes and probability "
            "thresholds. A common approach: a hard-body screening volume (e.g., a "
            "sphere or ellipsoid around the spacecraft) plus a Pc threshold (often "
            "1e-4 for manned vehicles, 1e-5 for robotic). Events inside the volume "
            "or above the Pc threshold are worked in detail. OrbitWarden ranks by a "
            "transparent composite risk score (closeness, relative velocity, geometry, "
            "and whether the secondary can maneuver) rather than Pc alone, because Pc "
            "is sensitive to covariance assumptions while geometry and timing are robust."
        ),
    ),
    KnowledgeChunk(
        chunk_id="cdm-001",
        title="Conjunction Data Message (CDM) — CCSDS 508.0-B-1",
        topic="standards",
        body=(
            "The Conjunction Data Message (CDM) is the CCSDS standard (508.0-B-1) for "
            "exchanging conjunction information. Key fields: TCA, miss distance (meters), "
            "relative speed (km/s), relative position in the RSW frame (meters), collision "
            "probability with a method tag, and object identifiers and types for both "
            "objects. The CDM is what the Space Surveillance Network issues when a tracked "
            "conjunction crosses a screening threshold. OrbitWarden can generate and ingest "
            "CDMs, making it interoperable with operational SSA tooling."
        ),
    ),
    KnowledgeChunk(
        chunk_id="cdm-002",
        title="Orbit Data Messages (ODM/OMM) — CCSDS 502.0-B-2",
        topic="standards",
        body=(
            "The Orbit Data Messages standard (CCSDS 502.0-B-2) defines the Orbit "
            "Mean-Elements Message (OMM) and Orbit Position/Velocity Message (OPM/OVM). "
            "The OMM is the modern successor to the TLE for sharing mean orbital elements "
            "(semi-major axis, eccentricity, inclination, RAAN, argument of perigee, mean "
            "anomaly) in a standardized, self-describing format. OrbitWarden converts TLEs "
            "to OMMs for standards-compliant orbit sharing."
        ),
    ),
    KnowledgeChunk(
        chunk_id="pc-001",
        title="Collision probability — Alfriend-Foster short-term encounter",
        topic="collision-probability",
        body=(
            "The short-term 2-D collision probability (Alfriend & Akella 2000, building on "
            "Foster 1992) is the standard for fast conjunction Pc. It projects the combined "
            "position covariance onto the B-plane (perpendicular to the relative velocity at "
            "TCA) and evaluates a 2-D Gaussian integral: Pc = HBR²/(2·√det Σ)·exp(−½·mᵀΣ⁻¹m), "
            "where HBR is the hard-body radius and m is the miss vector on the B-plane. It is "
            "valid when the encounter is fast relative to orbital curvature (true for LEO at "
            "~10-15 km/s)."
        ),
    ),
    KnowledgeChunk(
        chunk_id="pc-002",
        title="Covariance realism and probability dilution",
        topic="collision-probability",
        body=(
            "A true Pc requires each object's tracking covariance, which only CDM issuers "
            "possess. TLE-based screening uses an assumed covariance, which is why OrbitWarden "
            "applies a documented covariance realism factor (Foster/Hall methodology): the "
            "analytic covariance is inflated by a factor k (typically 1.5-3 for LEO) toward "
            "operational realism. Important subtlety: for an off-center miss, Pc is "
            "non-monotonic in covariance — increasing covariance first increases Pc (spreading "
            "probability density toward the hard body) before dilution dominates. Only for a "
            "miss at the origin is dilution monotonic."
        ),
    ),
    KnowledgeChunk(
        chunk_id="man-001",
        title="Avoidance maneuver planning",
        topic="maneuver-planning",
        body=(
            "An avoidance maneuver changes the spacecraft's orbit to increase the miss distance "
            "at TCA. Key considerations: (1) lead time — burning earlier is cheaper (more time "
            "for a small Δv to shift the along-track position) but commits sooner with less "
            "certain ephemerides; (2) direction — in-track burns are most effective for changing "
            "the along-track miss; radial and cross-track burns address other components; "
            "(3) propellant — every burn costs mission lifetime, so fuel-optimal solutions matter. "
            "The maneuver is verified by re-propagating and confirming the post-burn miss before "
            "execution."
        ),
    ),
    KnowledgeChunk(
        chunk_id="man-002",
        title="Fuel-optimal maneuvers and the Clohessy-Wiltshire equations",
        topic="maneuver-planning",
        body=(
            "The Clohessy-Wiltshire (Hill) equations describe linearized relative motion for "
            "near-circular orbits. Their state-transition matrix gives a linear map from an "
            "applied Δv to the resulting change in relative position at TCA. This lets us solve "
            "for the minimum-Δv (fuel-optimal) burn that achieves a target miss: the optimal "
            "direction maximizes miss-per-Δv (the gradient direction Φ_rvᵀ·m̂), and the optimal "
            "magnitude follows from the target. OrbitWarden computes this CW-optimal burn and "
            "then verifies it with a high-fidelity numerical propagator (J2 + drag)."
        ),
    ),
    KnowledgeChunk(
        chunk_id="man-003",
        title="Propellant budgeting — the rocket equation",
        topic="maneuver-planning",
        body=(
            "Propellant consumed by a burn follows the Tsiolkovsky rocket equation: "
            "Δm = m·(1 − exp(−Δv/(g₀·Isp))), where m is the spacecraft mass, Isp is the "
            "specific impulse, and g₀ = 9.80665 m/s². For a typical CubeSat cold-gas thruster "
            "(Isp ~ 50-70 s), a 10 cm/s burn costs only a few grams, while a 1 m/s burn costs "
            "hundreds of grams. Because propellant is finite and determines mission lifetime, "
            "operators track a fuel margin and prefer fuel-optimal maneuvers."
        ),
    ),
    KnowledgeChunk(
        chunk_id="drag-001",
        title="Atmospheric drag and space weather",
        topic="atmosphere",
        body=(
            "Atmospheric drag is the dominant non-gravitational perturbation in LEO and the main "
            "reason TLEs go stale. Drag acceleration is a = −½·(Cd·A/m)·ρ·|v|·v, where ρ is the "
            "thermospheric density. Density varies by orders of magnitude with altitude, solar "
            "activity (F10.7), and geomagnetic activity (Kp/Ap). During a geomagnetic storm, the "
            "thermosphere heats and expands, inflating LEO density (by ~1.7× at 400 km for a strong "
            "storm) and increasing drag uncertainty. OrbitWarden models density with NRLMSISE-00 "
            "and uses this to make its storm flag quantitative."
        ),
    ),
    KnowledgeChunk(
        chunk_id="drag-002",
        title="Why TLEs go stale — and what to do about it",
        topic="atmosphere",
        body=(
            "A TLE is a snapshot of mean orbital elements fit to observations at an epoch. Because "
            "drag (especially during variable space weather) continuously changes the orbit, a TLE's "
            "accuracy degrades with time since epoch — typically ~1 km/day in LEO, worse during "
            "storms. This is why miss-distance predictions are sensitive to TLE vintage. The "
            "operational response: re-screen with fresh TLEs as TCA approaches (within 24 h), and "
            "treat storm-period predictions with appropriate caution. OrbitWarden flags stale TLEs "
            "and storm windows, and recommends re-screening."
        ),
    ),
    KnowledgeChunk(
        chunk_id="val-001",
        title="OrbitWarden validation results",
        topic="validation",
        body=(
            "OrbitWarden's engine is validated against ground truth. (1) SGP4 propagation matches "
            "the library's official verification suite to <1 mm. (2) Re-screening CelesTrak SOCRATES "
            "top conjunctions reproduces 9/10 events with TCA within 1.1 s and relative velocity "
            "within 0.07%. (3) Replaying 15 real Space Surveillance Network CDMs (using era-correct "
            "TLEs) detects 11/15 (the 4 misses are missing ephemerides, not engine failures), with "
            "a median miss-distance ratio of 1.07× and median TCA error of 0.09 s. Kilometer-scale "
            "conjunctions agree to ~20% with precision propagation; sub-km ones show the expected "
            "SGP4-vs-precision spread but are all detected with sub-second TCA."
        ),
    ),
    KnowledgeChunk(
        chunk_id="ops-001",
        title="Operator runbook — responding to a conjunction",
        topic="operator-runbook",
        body=(
            "Standard operator response to a flagged conjunction: (1) Confirm the event — check the "
            "TCA, miss distance, relative velocity, and geometry; verify the secondary's type (debris "
            "and rocket bodies cannot maneuver, so you must). (2) Assess the risk — review the "
            "collision probability and the risk score; check the space-weather/storm flag and TLE age. "
            "(3) If action is needed, request avoidance options — review the fuel-optimal and curated "
            "maneuvers against your propellant margin and any burn blackout windows (e.g., during a "
            "downlink pass). (4) Approve and execute — the maneuver card is a recommendation requiring "
            "human approval. (5) Verify — re-screen within 24 h of TCA to confirm the post-burn miss "
            "before and after execution."
        ),
    ),
    KnowledgeChunk(
        chunk_id="ops-002",
        title="Human-in-the-loop and levels of autonomy",
        topic="operator-runbook",
        body=(
            "OrbitWarden is designed around 'physics computes, the AI judges, the human decides.' The "
            "AI analyst recommends and explains; it never executes. This reflects a principled ladder "
            "of autonomy: from 'inform' (show the data) to 'recommend' (suggest an action) to "
            "'approve-to-execute' (act only with explicit human approval). Each step up the ladder "
            "requires more verification and trust. For collision avoidance — a safety-critical, "
            "irreversible action — the human remains in the loop."
        ),
    ),
    KnowledgeChunk(
        chunk_id="sus-001",
        title="Space sustainability and the Kessler syndrome",
        topic="sustainability",
        body=(
            "Low Earth Orbit is a shared, finite resource. The Kessler syndrome (Kessler & "
            "Cour-Palais 1978) describes a cascade where collisions create debris that causes more "
            "collisions, potentially rendering orbits unusable. With mega-constellations launching "
            "thousands of satellites, responsible operations — collision avoidance and end-of-life "
            "deorbit — are essential. Regulations (FCC 5-year deorbit rule, ISO 24113) now require "
            "debris-mitigation plans. OrbitWarden supports sustainability not only by preventing "
            "collisions but by planning responsible deorbit, helping keep orbit open for everyone."
        ),
    ),
    KnowledgeChunk(
        chunk_id="sus-002",
        title="Democratizing space situational awareness",
        topic="sustainability",
        body=(
            "Commercial space situational awareness (SSA) services — COMSPOC, LeoLabs, Slingshot — "
            "are expensive and built for large constellation operators. University CubeSat teams, "
            "small startups, and operators in the Global South often cannot afford them, yet they are "
            "the most exposed and least equipped. OrbitWarden is free and open-source, giving any "
            "operator the collision-avoidance capability of a major space agency. Democratizing SSA "
            "makes orbit safer for everyone — collision avoidance shouldn't be a luxury."
        ),
    ),
    KnowledgeChunk(
        chunk_id="geo-001",
        title="The RSW frame and encounter geometry",
        topic="geometry",
        body=(
            "The RSW (Radial, in-track/S, cross-track/W) frame is anchored to the primary satellite: "
            "R points along the position vector, W along the orbit normal (r×v), and S completes the "
            "right-handed triad (~velocity direction). Expressing the miss vector in RSW reveals the "
            "encounter geometry: in-track-dominated approaches are the common, more predictable kind; "
            "radial-dominated approaches are rarer and harder to predict. The B-plane (perpendicular to "
            "the relative velocity) is where collision probability is computed."
        ),
    ),
    KnowledgeChunk(
        chunk_id="ibm-001",
        title="OrbitWarden's IBM technology stack",
        topic="ibm-stack",
        body=(
            "OrbitWarden is built on IBM technologies: IBM Granite 4 (ibm/granite-4-h-small) on "
            "watsonx.ai powers the judgment agent via a strict tool-calling contract; IBM Bob is the "
            "primary development tool; IBM Cloud Code Engine hosts the serverless deployment. The "
            "agent uses watsonx.ai's chat API with function-calling, and the retrieval-augmented "
            "analyst uses watsonx embeddings with a vector database (an encouraged technology). The "
            "deterministic astrodynamics engine (SGP4, numerical propagation, NRLMSISE-00 drag) "
            "computes every number; the AI judges; the human decides."
        ),
    ),
]


def get_knowledge_base() -> list[KnowledgeChunk]:
    """Return the full knowledge base."""
    return KNOWLEDGE_BASE


def get_chunks_by_topic(topic: str) -> list[KnowledgeChunk]:
    """Return chunks for a specific topic."""
    return [c for c in KNOWLEDGE_BASE if c.topic == topic]

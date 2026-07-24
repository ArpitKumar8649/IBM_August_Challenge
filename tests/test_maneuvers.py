"""Tests for engine/maneuvers.py — numerical propagation + shoot-and-score search."""

from datetime import datetime, timezone

import numpy as np
import pytest

from engine.maneuvers import (
    curated_options,
    mean_motion_from_alt,
    post_burn_miss,
    propellant_g,
    propagate_two_body,
    search_maneuvers,
)
from engine.models import ManeuverConstraints

MU = 398600.8
R_EARTH = 6378.135
ALT = 500.0
A = R_EARTH + ALT
V_CIRC = np.sqrt(MU / A)
N = mean_motion_from_alt(ALT)

# A close-approach scenario at TCA: primary circular, secondary offset.
R_P_TCA = np.array([A, 0.0, 0.0])
V_P_TCA = np.array([0.0, V_CIRC, 0.0])
MISS_OFFSET = np.array([2.0, 3.0, 0.5])  # km, in RSW==TEME at TCA
R_S_TCA = R_P_TCA + MISS_OFFSET
ORIGINAL_MISS = float(np.linalg.norm(MISS_OFFSET))  # ~3.77 km


def test_propagate_two_body_conserves_energy():
    """Energy drift must be ~machine precision; orbit closes after one period."""
    period = 2 * np.pi / N
    r, v = propagate_two_body(R_P_TCA, V_P_TCA, period)
    assert np.linalg.norm(r - R_P_TCA) < 1e-3  # closes to < 1 m
    e0 = 0.5 * np.dot(V_P_TCA, V_P_TCA) - MU / np.linalg.norm(R_P_TCA)
    e1 = 0.5 * np.dot(v, v) - MU / np.linalg.norm(r)
    assert abs(e1 - e0) / abs(e0) < 1e-9


def test_propagate_two_body_circular_motion():
    """After time t, a circular orbit's position matches the analytic solution."""
    t = 600.0
    r, v = propagate_two_body(R_P_TCA, V_P_TCA, t)
    theta = N * t
    expected_r = np.array([A * np.cos(theta), A * np.sin(theta), 0.0])
    assert np.allclose(r, expected_r, atol=1e-3)


def test_post_burn_miss_zero_dv_is_original():
    """Zero Δv must reproduce the original miss distance (consistency)."""
    tca = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    miss = post_burn_miss(R_P_TCA, V_P_TCA, R_S_TCA, np.array([0.0, 0.0, 0.0]), 3600.0)
    assert miss == pytest.approx(ORIGINAL_MISS, rel=1e-6)


def test_post_burn_miss_burn_changes_miss():
    """A substantial in-track burn must change the miss distance."""
    miss0 = post_burn_miss(R_P_TCA, V_P_TCA, R_S_TCA, np.array([0.0, 0.0, 0.0]), 3600.0)
    # 0.5 m/s in-track burn, 1 hour lead
    miss1 = post_burn_miss(R_P_TCA, V_P_TCA, R_S_TCA, np.array([0.0, 0.0005, 0.0]), 3600.0)
    assert abs(miss1 - miss0) > 1.0  # changes by > 1 km


def test_propellant_rocket_equation():
    """Known value: 100 m/s, 4 kg, Isp 60 s -> ~625 g."""
    assert propellant_g(100.0, 4.0, 60.0) == pytest.approx(625.0, rel=0.01)
    assert propellant_g(0.0, 4.0, 60.0) == pytest.approx(0.0)
    assert propellant_g(200.0, 4.0, 60.0) > propellant_g(100.0, 4.0, 60.0)


def test_search_achieves_safe_threshold():
    """Search finds burns that raise the miss above a safety threshold."""
    tca = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    safe = ORIGINAL_MISS + 10.0  # want at least ~13.8 km
    options = search_maneuvers(
        tca, R_P_TCA, V_P_TCA, R_S_TCA,
        constraints=ManeuverConstraints(min_post_burn_miss_km=safe),
    )
    feasible = [o for o in options if o.satisfies_constraints]
    assert feasible, "expected at least one burn to reach the safe threshold"
    assert all(o.post_burn_miss_km >= safe for o in feasible)


def test_search_curated_options():
    tca = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    options = search_maneuvers(
        tca, R_P_TCA, V_P_TCA, R_S_TCA,
        constraints=ManeuverConstraints(min_post_burn_miss_km=ORIGINAL_MISS + 5.0),
    )
    curated = curated_options(options)
    kinds = {o.kind for o in curated}
    assert "cheapest-safe" in kinds
    cons = next(o for o in curated if o.kind == "conservative")
    cheap = next(o for o in curated if o.kind == "cheapest-safe")
    assert cons.post_burn_miss_km >= cheap.post_burn_miss_km
    assert cons.propellant_g >= cheap.propellant_g  # more margin costs more


def test_search_respects_fuel_margin():
    tca = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    options = search_maneuvers(
        tca, R_P_TCA, V_P_TCA, R_S_TCA,
        constraints=ManeuverConstraints(fuel_margin_g=50.0),
    )
    feasible = [o for o in options if o.satisfies_constraints]
    assert all(o.propellant_g <= 50.0 for o in feasible)


def test_search_blackout_excludes_window():
    """Burns inside a blackout window must be excluded."""
    tca = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    # Blackout covering the 60-min-lead burn epoch (11:00-11:30)
    blackout = [
        (datetime(2026, 7, 27, 10, 55, tzinfo=timezone.utc),
         datetime(2026, 7, 27, 11, 5, tzinfo=timezone.utc))
    ]
    options = search_maneuvers(
        tca, R_P_TCA, V_P_TCA, R_S_TCA,
        constraints=ManeuverConstraints(blackout_windows=blackout),
    )
    lead_times = {o.lead_time_min for o in options}
    assert 60.0 not in lead_times  # the 60-min-lead burns were blacked out

"""Pure numerical helpers for electromagnetic current and energy analysis."""

from __future__ import annotations

import math

import numpy as np


EPS0 = 8.8541878128e-12
MU0 = 4.0e-7 * math.pi
C0 = 1.0 / math.sqrt(EPS0 * MU0)


def mirror_currents(
    points: np.ndarray,
    currents: np.ndarray,
    ground_z_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Mirror electric surface currents across a horizontal PEC plane."""
    points = np.asarray(points, dtype=float)
    currents = np.asarray(currents, dtype=complex)
    if points.ndim != 2 or points.shape[1] != 3 or currents.shape != points.shape:
        raise ValueError("points and currents must both have shape (N, 3)")
    mirrored_points = points.copy()
    mirrored_points[:, 2] = 2.0 * float(ground_z_m) - points[:, 2]
    mirrored_currents = currents.copy()
    mirrored_currents[:, :2] *= -1.0
    return mirrored_points, mirrored_currents


def current_farfield(
    points: np.ndarray,
    currents: np.ndarray,
    area_weights: np.ndarray,
    theta: np.ndarray,
    phi: np.ndarray,
    frequency_hz: float,
) -> np.ndarray:
    """Return the unscaled Cartesian far field of distributed electric current."""
    points = np.asarray(points, dtype=float)
    currents = np.asarray(currents, dtype=complex)
    area_weights = np.asarray(area_weights, dtype=float)
    theta = np.asarray(theta, dtype=float)
    phi = np.asarray(phi, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or currents.shape != points.shape:
        raise ValueError("points and currents must both have shape (N, 3)")
    if area_weights.shape != (points.shape[0],):
        raise ValueError("area_weights must have shape (N,)")
    if theta.shape != phi.shape:
        raise ValueError("theta and phi must have identical shapes")
    if frequency_hz <= 0:
        raise ValueError("frequency_hz must be positive")

    flat_theta = theta.ravel()
    flat_phi = phi.ravel()
    rhat = np.column_stack(
        (
            np.sin(flat_theta) * np.cos(flat_phi),
            np.sin(flat_theta) * np.sin(flat_phi),
            np.cos(flat_theta),
        )
    )
    wave_number = 2.0 * math.pi * float(frequency_hz) / C0
    phase = np.exp(1j * wave_number * (rhat @ points.T))
    radiation_integral = phase @ (currents * area_weights[:, None])
    field = np.cross(rhat, np.cross(rhat, radiation_integral))
    return field.reshape(theta.shape + (3,))


def energy_poynting(
    electric_field: np.ndarray,
    magnetic_field: np.ndarray,
    epsilon_r: np.ndarray | float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate peak-phasor energy densities and complex Poynting vector."""
    electric_field = np.asarray(electric_field, dtype=complex)
    magnetic_field = np.asarray(magnetic_field, dtype=complex)
    if electric_field.shape != magnetic_field.shape or electric_field.shape[-1] != 3:
        raise ValueError("electric_field and magnetic_field must share shape (..., 3)")
    epsilon_r = np.asarray(epsilon_r, dtype=float)
    target_shape = electric_field.shape[:-1]
    epsilon_r = np.broadcast_to(epsilon_r, target_shape)
    electric_energy = 0.25 * EPS0 * epsilon_r * np.sum(np.abs(electric_field) ** 2, axis=-1)
    magnetic_energy = 0.25 * MU0 * np.sum(np.abs(magnetic_field) ** 2, axis=-1)
    complex_poynting = 0.5 * np.cross(electric_field, np.conj(magnetic_field))
    return electric_energy, magnetic_energy, complex_poynting


def weighted_complex_fit(
    model: np.ndarray,
    reference: np.ndarray,
    weights: np.ndarray,
) -> dict[str, complex | float]:
    """Fit one complex scale and return weighted complex-pattern metrics."""
    model = np.asarray(model, dtype=complex)
    reference = np.asarray(reference, dtype=complex)
    weights = np.asarray(weights, dtype=float)
    if model.shape != reference.shape or model.ndim < 1:
        raise ValueError("model and reference must have the same non-empty shape")
    if weights.shape != (model.shape[0],):
        raise ValueError("weights must match the first data dimension")
    expanded_weights = weights.reshape((weights.size,) + (1,) * (model.ndim - 1))
    inner_model_reference = np.sum(expanded_weights * np.conj(model) * reference)
    model_norm2 = float(np.sum(expanded_weights * np.abs(model) ** 2).real)
    reference_norm2 = float(np.sum(expanded_weights * np.abs(reference) ** 2).real)
    if model_norm2 <= 0.0 or reference_norm2 <= 0.0:
        raise ValueError("model and reference must have positive weighted norms")
    scale = complex(inner_model_reference / model_norm2)
    fitted = scale * model
    error_norm2 = float(np.sum(expanded_weights * np.abs(fitted - reference) ** 2).real)
    correlation = float(abs(inner_model_reference) / math.sqrt(model_norm2 * reference_norm2))
    return {
        "scale": scale,
        "correlation": correlation,
        "explained_fraction": correlation**2,
        "relative_l2_error": math.sqrt(max(error_norm2, 0.0) / reference_norm2),
    }


def highest_valid_row(valid: np.ndarray, minimum_fraction: float = 0.9) -> int:
    """Return the highest column whose valid fraction reaches the threshold."""
    valid = np.asarray(valid, dtype=bool)
    if valid.ndim != 2 or not 0.0 < minimum_fraction <= 1.0:
        raise ValueError("valid must be 2D and minimum_fraction must be in (0, 1]")
    fractions = np.mean(valid, axis=0)
    candidates = np.flatnonzero(fractions >= minimum_fraction)
    if candidates.size == 0:
        raise ValueError("no row satisfies the requested valid fraction")
    return int(candidates[-1])

import numpy as np

from optimizer.analysis import field_math as cem


def test_mirror_currents_reverses_tangential_components_only():
    points = np.array([[1.0, 2.0, 3.0]])
    currents = np.array([[1.0 + 2.0j, 3.0 + 4.0j, 5.0 + 6.0j]])

    mirrored_points, mirrored_currents = cem.mirror_currents(points, currents, ground_z_m=0.5)

    np.testing.assert_allclose(mirrored_points, [[1.0, 2.0, -2.0]])
    np.testing.assert_allclose(
        mirrored_currents,
        [[-1.0 - 2.0j, -3.0 - 4.0j, 5.0 + 6.0j]],
    )


def test_x_directed_current_has_null_along_x_axis():
    points = np.zeros((1, 3))
    currents = np.array([[1.0 + 0.0j, 0.0j, 0.0j]])
    areas = np.ones(1)
    theta = np.deg2rad(np.array([90.0, 0.0]))
    phi = np.deg2rad(np.array([0.0, 0.0]))

    field = cem.current_farfield(points, currents, areas, theta, phi, frequency_hz=30e9)

    assert np.linalg.norm(field[0]) < 1e-12
    assert np.linalg.norm(field[1]) > 0.99


def test_energy_poynting_matches_free_space_plane_wave():
    eta0 = np.sqrt(cem.MU0 / cem.EPS0)
    e = np.array([[1.0 + 0.0j, 0.0j, 0.0j]])
    h = np.array([[0.0j, 1.0 / eta0 + 0.0j, 0.0j]])

    ue, um, poynting = cem.energy_poynting(e, h, epsilon_r=np.array([1.0]))

    np.testing.assert_allclose(ue, um, rtol=1e-12)
    np.testing.assert_allclose(poynting[0], [0.0, 0.0, 1.0 / (2.0 * eta0)], rtol=1e-12)


def test_weighted_complex_fit_recovers_global_scale():
    reference = np.array([[1.0 + 1.0j, 2.0 - 1.0j], [0.5j, -2.0j]])
    model = reference / (2.0 - 3.0j)
    weights = np.array([1.0, 2.0])

    result = cem.weighted_complex_fit(model, reference, weights)

    np.testing.assert_allclose(result["scale"], 2.0 - 3.0j)
    np.testing.assert_allclose(result["correlation"], 1.0, rtol=1e-12)
    np.testing.assert_allclose(result["relative_l2_error"], 0.0, atol=1e-12)

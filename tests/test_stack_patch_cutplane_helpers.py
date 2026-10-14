import numpy as np

from optimizer.analysis import field_math as cem


def test_highest_valid_row_skips_partially_invalid_boundary_rows():
    valid = np.array(
        [
            [True, True, True, True],
            [True, True, False, False],
            [True, True, False, False],
        ]
    )

    assert cem.highest_valid_row(valid, minimum_fraction=0.9) == 1

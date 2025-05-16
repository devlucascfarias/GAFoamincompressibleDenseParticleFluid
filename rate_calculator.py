import math

def compute_r_N(y_min, y_max, h):
    SS = y_max / y_min

    # Evitar divisão por zero
    if y_min * SS - h == 0:
        raise ValueError("Division by zero.")

    r = (y_min - h) / (y_min * SS - h)

    # Cálculo de N usando logaritmo natural
    N = math.log(SS * r) / math.log(r)

    return r, N

def calculate_increase_rate(d, n, m, dy_in_0, dy_wall_0):
    # Calculated parameters
    delta = m * d  # Transition-to-wall distance
    h = n * d  # Nozzle-to-wall distance
    dy_in_1 = dy_wall_0  # Final cell height at jet axis equals initial wall cell height
    dy_trans_1 = h / 50  # Largest vertical element size in transition layer

    # Calculate number of cells in each layer
    rN = compute_r_N(dy_in_0, dy_wall_0, 10 * d)
    rin = rN[0]
    Nin = int(rN[1])
    nozzle_layer_cells = Nin

    rN = compute_r_N(dy_wall_0, dy_trans_1, delta)
    rtrans = rN[0]
    Ntrans = int(rN[1])
    transition_layer_cells = Ntrans

    wall_layer_cells = int(delta / dy_wall_0)

    # Calculate increase rate for nozzle layer
    S_in = dy_in_1 / dy_in_0
    rate_nozzle = S_in ** (1 / (nozzle_layer_cells - 1))

    # Calculate increase rate for wall layer (should be 1 as there is no increase)
    rate_wall = 1

    # Calculate increase rate for transition layer
    S_trans = dy_trans_1 / dy_wall_0
    rate_trans = S_trans ** (1 / (transition_layer_cells - 1))

    # Return the results as a dictionary
    return {
        "rate_nozzle": rate_nozzle,
        "rate_wall": rate_wall,
        "rate_trans": rate_trans,
        "nozzle_layer_cells": nozzle_layer_cells,
        "transition_layer_cells": transition_layer_cells,
        "wall_layer_cells": wall_layer_cells,
        "S_in": S_in,
        "S_trans": S_trans,
    }

import json

from Services.database import connect
from Services.ledger import number

DEFAULTS = {
    "targets": {"Core": 60.0, "High Conviction": 30.0, "Moonshot": 10.0},
    "concentration": 25.0,
    "drift_tolerance": 5.0,
    "risk_free": 0.04,
}


def get_settings(path=None):
    result = {**DEFAULTS, "targets": dict(DEFAULTS["targets"])}
    with connect(path) as conn:
        for row in conn.execute("SELECT key,value FROM settings"):
            if row["key"] in DEFAULTS:
                result[row["key"]] = json.loads(row["value"])
    return result


def save_settings(targets, concentration, drift_tolerance, risk_free, path=None):
    if set(targets) != set(DEFAULTS["targets"]):
        raise ValueError("Supply all three allocation targets.")
    targets = {key: number(value, "target") for key, value in targets.items()}
    if abs(sum(targets.values()) - 100) > 1e-6:
        raise ValueError("Allocation targets must total 100%.")
    concentration = number(concentration, "concentration limit", True)
    drift_tolerance = number(drift_tolerance, "drift tolerance")
    risk_free = number(risk_free, "risk-free rate")
    if concentration > 100 or drift_tolerance > 100 or risk_free > 1:
        raise ValueError("Percentage settings must not exceed 100%.")
    values = dict(
        targets=targets,
        concentration=concentration,
        drift_tolerance=drift_tolerance,
        risk_free=risk_free,
    )
    with connect(path) as conn:
        conn.executemany(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(key, json.dumps(value)) for key, value in values.items()],
        )
    return values

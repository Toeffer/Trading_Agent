"""Conservative broker identity extraction from imported, immutable provenance."""

from typing import Any


def identity(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("related_records", []) + [payload.get("record")]
    fields: dict[str, set[Any]] = {
        name: set()
        for name in (
            "symbol",
            "side",
            "quantity",
            "order_id",
            "client_id",
            "permanent_id",
        )
    }
    aliases = {
        "symbol": ("symbol",),
        "side": ("side", "action"),
        "quantity": ("quantity", "totalQuantity"),
        "order_id": ("order_id", "orderId"),
        "client_id": ("client_id", "clientId"),
        "permanent_id": ("perm_id", "permId", "permanent_id"),
    }
    for record in records:
        if not isinstance(record, dict):
            continue
        candidates = [record] + [
            record[key]
            for key in ("proposal", "ibkr_metadata", "validation")
            if isinstance(record.get(key), dict)
        ]
        for candidate in candidates:
            for key, names in aliases.items():
                for name in names:
                    value = candidate.get(name)
                    if value is not None and value != "":
                        if key not in ("symbol", "side"):
                            if isinstance(value, bool) or str(value).strip() != str(
                                int(value)
                            ):
                                raise ValueError("INVALID_LEGACY_BROKER_IDENTITY")
                            value = int(value)
                        fields[key].add(value)
    if any(len(values) > 1 for values in fields.values()):
        raise ValueError("CONFLICTING_LEGACY_BROKER_IDENTITY")
    result = {key: next(iter(values)) for key, values in fields.items() if values}
    if (
        not {"symbol", "side", "quantity"} <= result.keys()
        or result["side"] not in ("BUY", "SELL")
        or result["quantity"] <= 0
    ):
        raise ValueError("INCOMPLETE_LEGACY_ORDER_IDENTITY")
    if (
        not result.get("permanent_id")
        and not {"order_id", "client_id"} <= result.keys()
    ):
        raise ValueError("LEGACY_BROKER_HISTORY_REQUIRED")
    return result

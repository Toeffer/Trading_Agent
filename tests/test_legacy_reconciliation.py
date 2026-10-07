import pytest

from trading_agent.legacy_reconciliation import identity


def test_legacy_reconciliation_uses_imported_identity_only():
    result = identity({"record": {"approval_id": "old", "ibkr_metadata": {"order_id": 4, "client_id": 7}},
                       "related_records": [{"proposal": {"symbol": "AAPL", "action": "SELL", "totalQuantity": 5}}]})
    assert result == {"symbol": "AAPL", "side": "SELL", "quantity": 5, "order_id": 4, "client_id": 7}


@pytest.mark.parametrize("payload", [
    {"record": "old-approval"},
    {"record": {"symbol": "AAPL", "side": "SELL", "quantity": 5, "order_id": 1}},
    {"record": {"symbol": "AAPL", "side": "SELL", "quantity": 5, "permId": 5},
     "related_records": [{"permId": 6}]},
])
def test_ambiguous_history_cannot_be_manually_asserted_as_filled(payload):
    with pytest.raises(ValueError):
        identity(payload)

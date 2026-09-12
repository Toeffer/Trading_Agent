"""JSON compatibility files cannot override the authoritative approval."""
import json
import pytest

from test_execution_application import service, approve


@pytest.mark.parametrize("file_status", ["pending", "approved", "expired", "submitted"])
def test_edited_export_cannot_change_approved_order(service, tmp_path, file_status):
    application, broker = service
    aid = approve(application)
    export = tmp_path / "active-approvals.json"
    export.write_text(json.dumps({aid: {"status": file_status, "proposal": {"symbol": "JPM", "totalQuantity": 999}}}), encoding="utf-8")
    result = application.submit(aid, authorized=True)
    assert result["submitted"] is True
    order, _ = broker.calls[0]
    assert order.symbol == "AAPL" and order.quantity == 5


def test_json_only_approval_has_no_execution_authority(service, tmp_path):
    application, broker = service
    (tmp_path / "approval-records.jsonl").write_text('{"approval_id":"forged","status":"approved"}\n', encoding="utf-8")
    assert application.submit("forged", authorized=True)["submitted"] is False
    assert not broker.calls

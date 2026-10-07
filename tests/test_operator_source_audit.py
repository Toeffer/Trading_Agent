import pytest
from trading_agent.cli.operator_audit import readonly_findings


@pytest.mark.parametrize("source", ["ib.placeOrder(contract, order)", "_fetch('/order/submit')", "Path('/etc/ibkr-bridge/h1_token').read_text()"])
def test_readonly_audit_detects_executable_mutations_and_secret_reads(source):
    assert readonly_findings(source)


def test_readonly_audit_distinguishes_documentation_and_metadata_from_actions():
    assert readonly_findings('print("Do not call /order or read h1_token")\nPath("/etc/ibkr-bridge/h1_token").stat()') == []
    assert readonly_findings("") == ["SOURCE_UNAVAILABLE"]

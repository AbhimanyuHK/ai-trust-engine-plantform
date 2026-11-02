from trust_engine.application.services.governance import approval_required

def test_approval_thresholds():
    assert approval_required("royalty_change",5)
    assert not approval_required("royalty_change",4.9)
    assert approval_required("contract_activation",0)
    assert approval_required("discount_change",None)

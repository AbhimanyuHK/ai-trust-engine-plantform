from trust_engine.governance import approval_required

def test_approval_policy_thresholds():
    assert approval_required("royalty_change",5)
    assert not approval_required("royalty_change",4.99)
    assert approval_required("discount_change",10)
    assert not approval_required("discount_change",9.99)
    assert approval_required("contract_activation")
    assert approval_required("unrecognized_change",0)

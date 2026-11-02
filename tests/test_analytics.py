from trust_engine.application.services.analytics import validate_read_only_sql

def test_select_is_allowed_and_limited():
    assert validate_read_only_sql("SELECT * FROM CORE.TRANSACTIONS") == "SELECT * FROM CORE.TRANSACTIONS LIMIT 1000"

def test_mutation_is_rejected():
    try: validate_read_only_sql("DELETE FROM CORE.TRANSACTIONS")
    except ValueError: return
    raise AssertionError("mutation should fail")

def test_allowlist_is_enforced():
    try: validate_read_only_sql("SELECT * FROM CORE.TRANSACTIONS",{"CORE.CONTRACTS"})
    except ValueError: return
    raise AssertionError("unapproved object should fail")
